"""Validazione dei vincoli dell istanza normalizzata."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Mapping, Sequence

from energy_planner.core.normalization import minutes_to_slot, snap_end, snap_start, SLOT_MINUTES

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Livelli di gravita per i problemi riscontrati."""

    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(slots=True)
class ValidationIssue:
    """Descrive un problema rilevato dal validatore."""

    severity: Severity
    message: str
    suggestion: str


@dataclass(slots=True)
class Activity:
    """Rappresenta un attivita pronta per la validazione."""

    name: str
    duration_minutes: int
    window_start: int
    window_end: int
    employees: float
    machine: str | None
    precedences: Sequence[str]


@dataclass(slots=True)
class ValidationInput:
    """Dati richiesti dal validatore."""

    activities: Sequence[Activity]
    workforce_per_slot: Sequence[float]
    price_per_slot: Sequence[float]
    objective: str
    machine_powers: Mapping[str, float]
    contractual_power: float | None = None
    enforce_power_hard: bool = True


@dataclass(slots=True)
class ValidationResult:
    """Output del validatore."""

    issues: List[ValidationIssue]


def validate(input: ValidationInput) -> ValidationResult:
    issues: List[ValidationIssue] = []

    issues.extend(_validate_windows(input.activities))
    issues.extend(_validate_precedences(input.activities))
    issues.extend(_validate_workforce(input.activities, input.workforce_per_slot))
    issues.extend(_validate_machines(input.activities))
    issues.extend(
        _validate_power_limit(
            input.activities,
            machine_powers=input.machine_powers,
            contractual_power=input.contractual_power,
            enforce_hard=input.enforce_power_hard,
        )
    )

    return ValidationResult(issues=issues)


def _validate_windows(activities: Sequence[Activity]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for activity in activities:
        snapped_start = snap_start(activity.window_start)
        snapped_end = snap_end(activity.window_end)
        available = snapped_end - snapped_start
        if available < activity.duration_minutes:
            extra = activity.duration_minutes - available
            suggestion = (
                f"Attivita '{activity.name}': (A) allarga la finestra di +{extra} minuti, "
                f"(B) riduci la durata di {extra} minuti se compatibile."
            )
            issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    message=(
                        f"Attivita '{activity.name}' ha durata {activity.duration_minutes} min superiore alla finestra "
                        f"[{snapped_start},{snapped_end})."
                    ),
                    suggestion=suggestion,
                )
            )
    return issues


def _validate_precedences(activities: Sequence[Activity]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    graph: Dict[str, List[str]] = {activity.name: list(activity.precedences) for activity in activities}
    temp_mark: set[str] = set()
    perm_mark: set[str] = set()

    def visit(node: str, path: List[str]) -> None:
        if node in perm_mark:
            return
        if node in temp_mark:
            cycle_nodes = path + [node]
            cycle_text = " -> ".join(cycle_nodes)
            suggestion = (
                "Precedenze cicliche: (A) rimuovi il legame finale del ciclo, "
                "(B) inverti la precedenza su una coppia di attivita (es. scambia l'ordine tra le prime due del ciclo)."
            )
            issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Precedenze cicliche rilevate: {cycle_text}",
                    suggestion=suggestion,
                )
            )
            return
        temp_mark.add(node)
        for neighbor in graph.get(node, []):
            visit(neighbor, path + [node])
        temp_mark.remove(node)
        perm_mark.add(node)

    for activity in graph:
        visit(activity, [])
    return issues


def _validate_workforce(activities: Sequence[Activity], workforce_per_slot: Sequence[float]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    slot_demands = [0.0] * len(workforce_per_slot)
    for activity in activities:
        start_slot = minutes_to_slot(snap_start(activity.window_start))
        required_slots = max(1, activity.duration_minutes // SLOT_MINUTES)
        for offset in range(required_slots):
            slot = start_slot + offset
            if slot >= len(slot_demands):
                break
            slot_demands[slot] += activity.employees
    for idx, (demand, capacity) in enumerate(zip(slot_demands, workforce_per_slot)):
        if demand > capacity + 1e-6:
            extra = demand - capacity
            suggestion = (
                f"Workforce slot {idx}: (A) sposta un'attivita che pesa su questo slot, "
                f"(B) aumenta la capacita dello slot di almeno {extra:.1f} unita."
            )
            issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"Workforce insufficiente allo slot {idx}: richiesta {demand}, disponibile {capacity}.",
                    suggestion=suggestion,
                )
            )
    return issues


def _validate_machines(activities: Sequence[Activity]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    usage: Dict[str, List[tuple[int, int, str]]] = {}
    for activity in activities:
        if not activity.machine:
            continue
        start = snap_start(activity.window_start)
        end = snap_end(activity.window_end)
        usage.setdefault(activity.machine, []).append((start, end, activity.name))
    for machine, intervals in usage.items():
        intervals.sort()
        for i in range(len(intervals) - 1):
            current = intervals[i]
            nxt = intervals[i + 1]
            if current[1] > nxt[0]:
                suggestion = (
                    f"Macchina {machine}: (A) ripianifica l'attivita '{nxt[2]}' in un'altra fascia, "
                    "(B) valuta l'uso di una macchina alternativa per una delle due attivita."
                )
                issues.append(
                    ValidationIssue(
                        severity=Severity.ERROR,
                        message=(
                            f"Macchina {machine}: attivita '{current[2]}' e '{nxt[2]}' si sovrappongono "
                            f"({current[0]}-{current[1]} vs {nxt[0]}-{nxt[1]})."
                        ),
                        suggestion=suggestion,
                    )
                )
    return issues


def _validate_power_limit(
    activities: Sequence[Activity],
    *,
    machine_powers: Mapping[str, float],
    contractual_power: float | None,
    enforce_hard: bool,
) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if contractual_power is None:
        return issues

    total_slots: Dict[int, float] = {}
    for activity in activities:
        if not activity.machine:
            continue
        power = float(machine_powers.get(activity.machine, 0.0))
        if power <= 0:
            continue
        start = minutes_to_slot(snap_start(activity.window_start))
        required_slots = max(1, activity.duration_minutes // SLOT_MINUTES)
        for offset in range(required_slots):
            slot = start + offset
            total_slots[slot] = total_slots.get(slot, 0.0) + power
    for slot, total in total_slots.items():
        if total > contractual_power + 1e-6:
            severity = Severity.ERROR if enforce_hard else Severity.WARNING
            suggestion = (
                f"Slot {slot}: (A) sposta o ritarda una delle attivita che usa la macchina in questa fascia, "
                "(B) riduci il carico o richiedi aumento della potenza contrattuale."
            )
            issues.append(
                ValidationIssue(
                    severity=severity,
                    message=(
                        f"Potenza contrattuale superata allo slot {slot}: carico {total:.2f} kW "
                        f"contro limite {contractual_power:.2f} kW."
                    ),
                    suggestion=suggestion,
                )
            )
    return issues


__all__ = [
    "Severity",
    "ValidationIssue",
    "Activity",
    "ValidationInput",
    "ValidationResult",
    "validate",
]
