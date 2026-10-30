"""Compilazione dell istanza schedulabile a partire dal TripleStore."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from energy_planner.core.normalization import (
    SLOT_MINUTES,
    build_price_series,
    build_workforce_series,
    minutes_to_slot,
    parse_time,
    snap_end,
    snap_start,
)
from energy_planner.core.triple_store import Triple, TripleStore

logger = logging.getLogger(__name__)


def compile_instance(store: TripleStore) -> Dict[str, Any]:
    """Converte il contenuto del TripleStore in un dizionario compatibile con lo schema JSON."""
    slot_minutes = _extract_slot_minutes(store)
    horizon_hours = _extract_horizon_hours(store)

    price_per_slot = _extract_price_vector(store, horizon_hours)
    workforce_per_slot = _extract_workforce_vector(store, horizon_hours, len(price_per_slot))

    total_slots = _resolve_total_slots(price_per_slot, workforce_per_slot, horizon_hours)

    machines = _extract_machines(store)
    activities = _extract_activities(store, slot_minutes, total_slots)
    locks = _extract_locks(store)
    objective = _extract_objective(store)
    assumptions = _extract_assumptions(store)

    instance: Dict[str, Any] = {
        "time": {"slot_minutes": slot_minutes, "slots": total_slots},
        "pricing": price_per_slot,
        "workforce": workforce_per_slot,
        "machines": machines,
        "activities": activities,
        "objective": objective,
        "assumptions": assumptions,
    }
    if locks:
        instance["locks"] = locks

    logger.debug(
        "Istanza compilata: slots=%s, activities=%s, machines=%s, objective=%s",
        total_slots,
        len(activities),
        len(machines),
        objective,
    )
    return instance


def _extract_slot_minutes(store: TripleStore) -> int:
    for triple in store.query(subject_prefix="time", relation="slot_minutes"):
        try:
            value = int(triple.value)
            logger.debug("Slot minutes definiti via tripla: %s", value)
            return value
        except (ValueError, TypeError):
            logger.debug("Slot minutes non interpretabili: %s", triple.value)
            continue
    logger.debug("Slot minutes non specificati, uso default %s", SLOT_MINUTES)
    return SLOT_MINUTES


def _extract_horizon_hours(store: TripleStore) -> int | None:
    for triple in store.query(subject_prefix="horizon", relation="hours"):
        try:
            value = int(triple.value)
            if value > 0:
                logger.debug("Horizon definito: %s ore", value)
                return value
        except (ValueError, TypeError):
            logger.debug("Horizon non interpretabile: %s", triple.value)
            continue
    return None


def _extract_price_vector(store: TripleStore, horizon_hours: int | None) -> List[float]:
    per_slot: List[float] | None = None
    per_hour: List[float] | None = None

    for triple in store.query(subject_prefix="price"):
        if triple.relation == "per_slot" and isinstance(triple.value, list):
            per_slot = [float(v) for v in triple.value]
            logger.debug("Serie prezzi per slot trovata (len=%s)", len(per_slot))
            break
        if triple.relation == "per_hour" and isinstance(triple.value, list):
            per_hour = [float(v) for v in triple.value]

    if per_slot is not None:
        return per_slot

    hours = horizon_hours or (len(per_hour) if per_hour else 0) or 24
    logger.debug("Costruisco serie prezzi partendo da 24 valori (horizon=%s)", hours)
    return build_price_series(horizon_hours=hours, per_hour=per_hour)


def _extract_workforce_vector(
    store: TripleStore,
    horizon_hours: int | None,
    slots_from_price: int,
) -> List[float]:
    per_slot: List[float] | None = None
    shifts: List[Mapping[str, Any]] = []
    default_per_slot: float | None = None

    for triple in store.query(subject_prefix="workforce"):
        if triple.relation == "per_slot" and isinstance(triple.value, list):
            per_slot = [float(v) for v in triple.value]
            logger.debug("Serie workforce per slot trovata (len=%s)", len(per_slot))
            break
        if triple.relation == "shift" and isinstance(triple.value, Mapping):
            shifts.append(triple.value)
        if triple.relation == "default_per_slot":
            try:
                default_per_slot = float(triple.value)
            except (TypeError, ValueError):
                default_per_slot = None

    hours = horizon_hours
    if hours is None and slots_from_price:
        slots_per_hour = 60 // SLOT_MINUTES
        hours = math.ceil(slots_from_price / slots_per_hour)
    if hours is None:
        hours = 24

    if per_slot is not None:
        return per_slot

    kwargs: Dict[str, Any] = {"horizon_hours": hours}
    if shifts:
        kwargs["shifts"] = shifts
    if default_per_slot is not None:
        kwargs["default_per_slot"] = default_per_slot
    logger.debug("Costruisco serie workforce h=%s shifts=%s default=%s", hours, len(shifts), default_per_slot)
    return build_workforce_series(**kwargs)

# remainder unchanged

def _resolve_total_slots(
    price_per_slot: Sequence[float],
    workforce_per_slot: Sequence[float],
    horizon_hours: int | None,
) -> int:
    if price_per_slot:
        return len(price_per_slot)
    if workforce_per_slot:
        return len(workforce_per_slot)
    if horizon_hours is not None:
        return horizon_hours * (60 // SLOT_MINUTES)
    return 24 * (60 // SLOT_MINUTES)


def _extract_machines(store: TripleStore) -> List[Dict[str, Any]]:
    data: Dict[str, Dict[str, Any]] = {}
    for triple in store.query(subject_prefix="machine:"):
        machine_id = triple.subject.split(":", 1)[1]
        entry = data.setdefault(machine_id, {"id": machine_id, "name": machine_id, "power_kW": 0.0})
        if triple.relation == "name" and isinstance(triple.value, str):
            entry["name"] = triple.value
        elif triple.relation == "power_kW":
            try:
                entry["power_kW"] = float(triple.value)
            except (TypeError, ValueError):
                entry["power_kW"] = 0.0
    return sorted(data.values(), key=lambda item: item["id"])


def _clamp_slot(value: int, total_slots: int) -> int:
    return max(0, min(value, max(0, total_slots)))


def _extract_activities(store: TripleStore, slot_minutes: int, total_slots: int) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Triple]] = defaultdict(list)
    for triple in store.query(subject_prefix="activity:"):
        grouped[triple.subject].append(triple)

    activities: List[Dict[str, Any]] = []
    for subject, triples in sorted(grouped.items(), key=lambda item: item[0]):
        activity_id = subject.split(":", 1)[1]
        data: Dict[str, Any] = {
            "id": activity_id,
            "duration_slots": 1,
            "window_slots": [0, max(1, total_slots)],
            "employees": 0,
        }
        precedences: List[str] = []
        occurs_at_minutes: List[int] = []
        window_minutes: List[int] | None = None
        window_start_slot: int | None = None
        window_end_slot: int | None = None

        for triple in triples:
            relation = triple.relation
            value = triple.value
            if relation == "name" and isinstance(value, str):
                data["name"] = value
            elif relation in {"duration_slots", "duration_in_slots"}:
                try:
                    data["duration_slots"] = max(1, int(value))
                except (TypeError, ValueError):
                    continue
            elif relation in {"duration_min", "duration_minutes"}:
                try:
                    duration_minutes = int(value)
                    data["duration_slots"] = max(1, math.ceil(duration_minutes / slot_minutes))
                except (TypeError, ValueError):
                    continue
            elif relation == "window_slots" and isinstance(value, list) and len(value) == 2:
                try:
                    start_slot = _clamp_slot(int(value[0]), total_slots)
                    end_slot = _clamp_slot(int(value[1]), total_slots)
                    window_start_slot = start_slot
                    window_end_slot = end_slot
                except (TypeError, ValueError):
                    continue
            elif relation == "window" and isinstance(value, Mapping):
                try:
                    start_time = snap_start(parse_time(str(value["start"])))
                    end_time = snap_end(parse_time(str(value["end"])))
                    window_minutes = [start_time, end_time]
                except Exception:
                    continue
            elif relation == "occurs_at" and isinstance(value, str):
                try:
                    occurs_at_minutes.append(snap_start(parse_time(value)))
                except ValueError:
                    continue
            elif relation in {"employees", "people"}:
                try:
                    data["employees"] = float(value)
                except (TypeError, ValueError):
                    continue
            elif relation == "requires_machine" and isinstance(value, str):
                data["requires_machine"] = value
            elif relation == "precedes" and isinstance(value, str):
                precedences.append(value)
            elif relation == "precedes" and isinstance(value, list):
                precedences.extend(str(item) for item in value)

        if window_minutes is not None:
            start_slot = _clamp_slot(minutes_to_slot(window_minutes[0]), total_slots)
            end_slot = _clamp_slot(minutes_to_slot(window_minutes[1]), total_slots)
            window_start_slot = start_slot
            window_end_slot = end_slot
        elif occurs_at_minutes:
            start_slot = _clamp_slot(minutes_to_slot(min(occurs_at_minutes)), total_slots)
            window_start_slot = start_slot
            window_end_slot = start_slot + data["duration_slots"]

        duration_slots = data["duration_slots"]
        earliest_slot = window_start_slot if window_start_slot is not None else 0
        if earliest_slot > total_slots:
            earliest_slot = max(0, total_slots - duration_slots)

        if window_end_slot is None:
            window_end_slot = total_slots
        window_end_slot = max(earliest_slot + duration_slots, window_end_slot)
        window_end_slot = min(window_end_slot, total_slots)

        latest_start_slot = max(earliest_slot, window_end_slot - duration_slots)
        latest_start_slot = min(latest_start_slot, max(0, total_slots - duration_slots))

        data["window_slots"] = [earliest_slot, latest_start_slot]
        data["latest_start_slot"] = latest_start_slot
        data["window_end_slot"] = min(total_slots, latest_start_slot + duration_slots)

        if precedences:
            data["precedences"] = sorted(set(precedences))

        activities.append(data)
    return activities


def _extract_locks(store: TripleStore) -> List[Dict[str, Any]]:
    locks: List[Dict[str, Any]] = []
    for triple in store.query(subject_prefix="lock"):
        if triple.relation != "start_at" or not isinstance(triple.value, Mapping):
            continue
        activity = str(triple.value.get("activity")) if triple.value.get("activity") else None
        time_value = triple.value.get("time")
        if activity is None or time_value is None:
            continue
        try:
            minute = snap_start(parse_time(str(time_value))) if isinstance(time_value, str) else int(time_value)
        except (ValueError, TypeError):
            continue
        lock = {"activity": activity, "slot": minutes_to_slot(minute)}
        locks.append(lock)
    return locks


def _extract_objective(store: TripleStore) -> str:
    for triple in store.query(subject_prefix="objective", relation="primary"):
        value = str(triple.value)
        lowered = value.lower()
        if lowered in {"min_cost", "min_peak"}:
            return lowered
    return "min_cost"


def _extract_assumptions(store: TripleStore) -> List[str]:
    assumptions: List[str] = []
    for triple in store.query(subject_prefix="note", relation="assumption"):
        if isinstance(triple.value, str):
            assumptions.append(triple.value)
    return assumptions


__all__ = ["compile_instance"]
