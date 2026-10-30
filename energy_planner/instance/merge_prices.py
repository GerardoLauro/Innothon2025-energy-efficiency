from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence

from energy_planner.pricing.forecaster_adapter import expand_per_hour_to_per_slot


def _to_float_list(values: Iterable[Any]) -> List[float]:
    return [float(value) for value in values]


def _collapse_slots_to_hours(per_slot: Sequence[Any]) -> List[float]:
    if not per_slot:
        return []
    chunk = 12
    return [float(per_slot[idx]) for idx in range(0, len(per_slot), chunk)]


def inject_prices(instance: Dict[str, Any], pricing: Dict[str, Any], to_per_slot: bool = True) -> Dict[str, Any]:
    """Inject pricing information into an instance, normalizing representation."""
    if instance is None:
        instance = {}
    target = instance

    per_hour_raw = pricing.get("per_hour") if isinstance(pricing, dict) else None
    per_slot_raw = pricing.get("per_slot") if isinstance(pricing, dict) else None

    per_hour: List[float] = []
    if isinstance(per_hour_raw, Sequence) and not isinstance(per_hour_raw, (str, bytes)):
        per_hour = _to_float_list(per_hour_raw)

    if to_per_slot:
        if isinstance(per_slot_raw, Sequence) and not isinstance(per_slot_raw, (str, bytes)):
            per_slot = _to_float_list(per_slot_raw)
        else:
            if not per_hour:
                raise ValueError("Pricing data must include 'per_hour' or 'per_slot'.")
            per_slot = expand_per_hour_to_per_slot(per_hour)
        target["pricing"] = per_slot
    else:
        if not per_hour:
            if isinstance(per_slot_raw, Sequence) and not isinstance(per_slot_raw, (str, bytes)):
                per_hour = _collapse_slots_to_hours(per_slot_raw)
            else:
                raise ValueError("Pricing data must include 'per_hour' or 'per_slot'.")
        target["pricing"] = per_hour

    notes = target.get("notes")
    note_text = "Prezzi inseriti da Price_forecaster (o flat fallback)"
    if isinstance(notes, list) and note_text not in notes:
        notes.append(note_text)

    return target
