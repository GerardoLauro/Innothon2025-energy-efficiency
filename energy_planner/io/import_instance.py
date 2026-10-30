from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def idx_to_hhmm(idx: int, slot_min: int) -> str:
    """Converte un indice di slot nell'orario HH:MM corrispondente."""
    total_minutes = max(0, int(idx)) * int(slot_min)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def _machine_subject(identifier: Any) -> str:
    text = str(identifier)
    return text if text.startswith("machine:") else f"machine:{text}"


def _activity_subject(identifier: Any) -> str:
    text = str(identifier)
    return text if text.startswith("activity:") else f"activity:{text}"


def load_instance_as_triples(path: str) -> List[List[Any]]:
    """Carica l'istanza JSON e la converte in una lista di triplette [soggetto, relazione, valore]."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Istanza non trovata: {path}")

    data = json.loads(file_path.read_text(encoding="utf-8"))
    triples: List[List[Any]] = []

    time_data: Dict[str, Any] = data.get("time", {}) if isinstance(data, dict) else {}
    slot_minutes = int(time_data.get("slot_minutes", 5))
    triples.append(["time", "slot_minutes", slot_minutes])

    pricing = data.get("pricing")
    if isinstance(pricing, list):
        triples.append(["price", "per_slot", [float(item) for item in pricing]])

    workforce = data.get("workforce")
    if isinstance(workforce, list):
        triples.append(["workforce", "per_slot", [float(item) for item in workforce]])

    machines = data.get("machines", [])
    if isinstance(machines, list):
        for machine in machines:
            if not isinstance(machine, dict):
                continue
            mid = machine.get("id") or machine.get("name")
            if mid is None:
                continue
            subject = _machine_subject(mid)
            name = machine.get("name")
            if name is not None:
                triples.append([subject, "name", str(name)])
            power = machine.get("power_kW", machine.get("power_kw"))
            if power is not None:
                triples.append([subject, "power_kW", float(power)])

    activities = data.get("activities", [])
    if isinstance(activities, list):
        for activity in activities:
            if not isinstance(activity, dict):
                continue
            aid = activity.get("id")
            if aid is None:
                continue
            subject = _activity_subject(aid)
            duration_slots = activity.get("duration_slots")
            duration_slots_int = None
            if duration_slots is not None:
                duration_slots_int = int(duration_slots)
                triples.append(
                    [subject, "duration_min", duration_slots_int * slot_minutes]
                )
            window_slots = activity.get("window_slots")
            if isinstance(window_slots, list) and len(window_slots) == 2:
                start_idx = int(window_slots[0])
                latest_idx = int(window_slots[1])
                if duration_slots_int is None:
                    end_idx = latest_idx
                else:
                    end_idx = latest_idx + duration_slots_int
                triples.append(
                    [
                        subject,
                        "window",
                        {
                            "start": idx_to_hhmm(start_idx, slot_minutes),
                            "end": idx_to_hhmm(end_idx, slot_minutes),
                        },
                    ]
                )
            employees = activity.get("employees")
            if employees is not None:
                triples.append([subject, "employees", float(employees)])
            requires_machine = activity.get("requires_machine")
            if requires_machine:
                machine_subject = _machine_subject(requires_machine)
                triples.append([subject, "requires_machine", machine_subject])

    objective = data.get("objective")
    if isinstance(objective, str):
        normalized_obj = objective.strip().lower()
        if normalized_obj not in {"min_cost", "min_peak"}:
            normalized_obj = "min_cost"
        triples.append(["objective", "primary", normalized_obj])

    assumptions = data.get("assumptions")
    if isinstance(assumptions, list):
        for entry in assumptions:
            if entry is None:
                continue
            triples.append(["note", "assumption", str(entry)])

    return triples
