from __future__ import annotations

import inspect
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve()
PACKAGE_ROOT = HERE.parent
REPO_ROOT = HERE.parents[2]

from EnergyBot5.optimization.optimizer_core import load_instance
from EnergyBot5.optimization.Euris.scheduler import Instance as EurisInstance
from EnergyBot5.optimization.Euris.scheduler import Scheduler as EurisScheduler

BASELINE_ALIASES = (
    "initial_plan",
    "baseline_plan",
    "initial_schedule",
    "baseline",
    "schedule",
)

__all__ = ["run_heuristic_until_better", "to_euris_json"]

PlanDict = Dict[str, int]
PlanList = List[PlanDict]


def _read_json_dict(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_plan_items(items: Iterable[Any]) -> PlanList:
    plan: PlanList = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        activity = entry.get("activity")
        start = entry.get("start_slot")
        end = entry.get("end_slot")
        if activity is None:
            continue
        try:
            start_slot = int(start)
            end_slot = int(end)
        except (TypeError, ValueError):
            continue
        if end_slot < start_slot:
            continue
        plan.append(
            {
                "activity": str(activity),
                "start_slot": start_slot,
                "end_slot": end_slot,
            }
        )
    return plan


def _plan_from_container(container: Any) -> PlanList:
    if isinstance(container, dict):
        items = container.get("plan")
        if isinstance(items, list):
            return _normalize_plan_items(items)
    if isinstance(container, list):
        return _normalize_plan_items(container)
    return []


def _load_baseline_from_instance(instance_path: Path) -> PlanList:
    data = _read_json_dict(instance_path)
    if not isinstance(data, dict):
        return []
    for key in BASELINE_ALIASES:
        if key in data:
            plan = _plan_from_container(data[key])
            if plan:
                return plan
    return []


def _load_baseline_from_file(path: Path) -> Tuple[PlanList, Optional[Dict[str, Any]]]:
    if not path.exists():
        return [], None
    payload = _read_json_dict(path)
    if not isinstance(payload, dict):
        return [], None
    plan = _plan_from_container(payload)
    return plan, payload if plan else None


def _load_baseline(instance_path: Path) -> PlanList:
    plan = _load_baseline_from_instance(instance_path)
    if plan:
        return plan

    candidates = [
        REPO_ROOT / "out" / "baseline.json",
    ]
    for candidate in candidates:
        plan, _ = _load_baseline_from_file(candidate)
        if plan:
            return plan
    return []


def _compute_kpi(data: Dict[str, Any], plan: PlanList, objective: str) -> Optional[float]:
    if not plan:
        return None
    slots = int(data["slots"])
    pricing = data.get("pricing", [])
    load = [0.0] * slots
    powers = {a["id"]: float(a.get("power_kw", 0.0)) for a in data.get("activities", [])}
    for entry in plan:
        activity = entry["activity"]
        start = max(0, min(slots, int(entry["start_slot"])))
        end = max(start, min(slots, int(entry["end_slot"])))
        power = powers.get(activity, 0.0)
        if power == 0.0:
            continue
        for idx in range(start, end):
            load[idx] += power
    if objective == "min_cost":
        if not pricing:
            return None
        slot_hours = float(data.get("slot_hours", 1.0))
        total = 0.0
        for idx, value in enumerate(load):
            price = pricing[idx] if idx < len(pricing) else pricing[-1]
            total += value * float(price) * slot_hours
        return total
    return max(load) if load else 0.0


def _slot_to_time(slot: int, slot_minutes: int) -> str:
    total_minutes = slot * slot_minutes
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def _format_plan_for_output(plan: PlanList, slot_minutes: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for entry in sorted(plan, key=lambda item: (item["start_slot"], item["activity"])):
        start_slot = int(entry["start_slot"])
        end_slot = int(entry["end_slot"])
        rows.append(
            {
                "activity": entry["activity"],
                "start_slot": start_slot,
                "end_slot": end_slot,
                "start_time": _slot_to_time(start_slot, slot_minutes),
                "end_time": _slot_to_time(end_slot, slot_minutes),
            }
        )
    return rows


def _write_solution(out_path: Path, objective: str, plan: PlanList, value: float, slot_minutes: int) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "solver": "heuristic",
        "objective": objective,
        "objective_value": float(value),
        "plan": _format_plan_for_output(plan, slot_minutes),
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _resolve_dataset_path() -> Optional[str]:
    candidates: List[Path] = [
        REPO_ROOT / "EnergyBot5" / "optimization" / "Euris" / "test.parquet",
        REPO_ROOT / "out" / "test.parquet",
    ]
    env_value = os.environ.get("EURIS_DATA_PATH")
    if env_value:
        env_path = Path(env_value)
        if env_path.is_dir():
            env_path = env_path / "test.parquet"
        candidates.insert(0, env_path)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def to_euris_json(data: Dict[str, Any]) -> Dict[str, Any]:
    slot_minutes = int(data["slot_minutes"])
    if slot_minutes != 5:
        raise ValueError("Solo slot da 5 minuti supportati dall'euristica.")
    slots = int(data["slots"])
    slots_per_hour = 60 // slot_minutes
    if slots % slots_per_hour != 0:
        raise ValueError("Numero di slot non compatibile con slot da 5 minuti.")
    total_hours = slots // slots_per_hour
    prices = [float(p) for p in data.get("pricing", [])]
    if len(prices) != slots:
        raise ValueError("Lista prezzi incoerente con il numero di slot.")
    workforce_raw = data.get("workforce", [])
    if len(workforce_raw) != slots:
        raise ValueError("Workforce non coerente con il numero di slot.")
    employees_per_slot = [int(math.ceil(float(x))) for x in workforce_raw]
    machines_data = [
        {"id": mid, "power_kw": float(power)}
        for mid, power in sorted(data.get("machines_power", {}).items())
    ]
    activities_data: List[Dict[str, Any]] = []
    for activity in data.get("activities", []):
        machine_id = activity.get("machine")
        machines = [machine_id] if machine_id else []
        activities_data.append(
            {
                "id": activity["id"],
                "duration_slots": int(activity["dur"]),
                "earliest_start_slot": int(activity["earliest"]),
                "latest_start_slot": int(activity["latest"]),
                "power_kw": float(activity.get("power_kw", 0.0)),
                "employees": int(math.ceil(float(activity.get("employees", 0.0)))),
                "machines": machines,
            }
        )
    precedences = [[pred, succ] for pred, succ in data.get("precedences", [])]
    objective = str(data.get("objective", "min_cost")).lower()
    if objective not in ("min_cost", "min_peak"):
        objective = "min_cost"
    eur_objective = "energy_cost" if objective == "min_cost" else "peak_power"
    eur_json: Dict[str, Any] = {
        "delta_minutes": slot_minutes,
        "T_hours": total_hours,
        "objective": eur_objective,
        "prices_eur_per_kwh": prices,
        "employees_per_slot": employees_per_slot,
        "machines": machines_data,
        "activities": activities_data,
        "precedences": precedences,
    }
    contract = data.get("contract_power_kw")
    if contract is not None:
        eur_json["contract_power_kw"] = float(contract)
    return eur_json


def _find_dataset_param(signature: inspect.Signature) -> Optional[str]:
    for name, param in list(signature.parameters.items())[1:]:
        if param.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue
        lname = name.lower()
        if "model" in lname:
            continue
        if "dataset" in lname or ("data" in lname and "path" in lname) or lname.endswith("_path"):
            return name
    return None


def _build_run_kwargs(run_sig: inspect.Signature, seed: int) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if "improve" in run_sig.parameters:
        kwargs["improve"] = True
    if "seed" in run_sig.parameters:
        kwargs["seed"] = seed
    return kwargs


def _constructor_attempts(signature: inspect.Signature, dataset_path: Optional[str], seed: int) -> List[Dict[str, Any]]:
    attempts: List[Dict[str, Any]] = []
    dataset_param = _find_dataset_param(signature)
    seed_in_ctor = "seed" in signature.parameters
    if dataset_param and dataset_path and seed_in_ctor:
        attempts.append({dataset_param: dataset_path, "seed": seed})
    if seed_in_ctor:
        attempts.append({"seed": seed})
    if dataset_param and dataset_path:
        attempts.append({dataset_param: dataset_path})
    attempts.append({})
    unique_attempts: List[Dict[str, Any]] = []
    seen = set()
    for item in attempts:
        key = tuple(sorted(item.items()))
        if key in seen:
            continue
        seen.add(key)
        unique_attempts.append(item)
    return unique_attempts


def _parse_scheduler_result(result: Any) -> Tuple[Optional[Dict[str, int]], Optional[float]]:
    schedule = None
    value: Optional[float] = None
    if isinstance(result, tuple):
        if result:
            schedule = result[0]
            if len(result) > 1 and isinstance(result[1], (int, float)):
                value = float(result[1])
    elif isinstance(result, dict):
        schedule = result
    if not isinstance(schedule, dict):
        return None, value
    normalized: Dict[str, int] = {}
    for key, val in schedule.items():
        try:
            normalized[str(key)] = int(val)
        except (TypeError, ValueError):
            return None, value
    return normalized, value


def _plan_from_euris(eur_instance: Any, schedule: Dict[str, int]) -> PlanList:
    plan: PlanList = []
    activities = getattr(eur_instance, "activities", {})
    for activity_id, start in schedule.items():
        if activity_id not in activities:
            continue
        duration = int(getattr(activities[activity_id], "duration", 0))
        if duration <= 0:
            continue
        start_slot = int(start)
        end_slot = start_slot + duration
        plan.append(
            {
                "activity": str(activity_id),
                "start_slot": start_slot,
                "end_slot": end_slot,
            }
        )
    return sorted(plan, key=lambda item: (item["start_slot"], item["activity"]))


def _run_single_seed(
    scheduler_cls: Any,
    eur_instance: Any,
    seed: int,
    constructor_sig: inspect.Signature,
    run_sig: inspect.Signature,
    dataset_path: Optional[str],
) -> Tuple[PlanList, Optional[float]]:
    attempts = _constructor_attempts(constructor_sig, dataset_path, seed)
    run_kwargs_template = _build_run_kwargs(run_sig, seed)
    for ctor_kwargs in attempts:
        try:
            scheduler = scheduler_cls(eur_instance, **ctor_kwargs)
        except TypeError:
            continue
        except Exception:
            continue
        run_kwargs = dict(run_kwargs_template)
        try:
            result = scheduler.run(**run_kwargs)
        except TypeError:
            run_kwargs.pop("seed", None)
            try:
                result = scheduler.run(**run_kwargs)
            except TypeError:
                result = scheduler.run()
        except Exception:
            continue
        schedule, value = _parse_scheduler_result(result)
        if schedule is None:
            continue
        plan = _plan_from_euris(eur_instance, schedule)
        if plan:
            return plan, value
    return [], None


def _normalize_objective(requested: str, fallback: str) -> Tuple[str, str]:
    req = (requested or "").strip().lower()
    if req not in ("min_cost", "min_peak"):
        req = (fallback or "").strip().lower()
    if req not in ("min_cost", "min_peak"):
        req = "min_cost"
    eur = "energy_cost" if req == "min_cost" else "peak_power"
    return req, eur


def run_heuristic_until_better(
    instance_path: str,
    out_path: str,
    objective: str,
    wallclock_sec: int = 30,
) -> str:
    instance_file = Path(instance_path).resolve()
    output_file = Path(out_path).resolve()
    wallclock = max(1, int(wallclock_sec))
    deadline = time.time() + wallclock

    data = load_instance(str(instance_file))
    objective_norm, eur_objective = _normalize_objective(
        objective,
        str(data.get("objective", "min_cost")),
    )
    baseline_plan = _load_baseline(instance_file)
    baseline_value = _compute_kpi(data, baseline_plan, objective_norm)
    slot_minutes = int(data["slot_minutes"])

    eur_json = to_euris_json(data)
    eur_json["objective"] = eur_objective
    eur_instance = EurisInstance(eur_json)

    dataset_path = _resolve_dataset_path()
    constructor_sig = inspect.signature(EurisScheduler)
    run_sig = inspect.signature(EurisScheduler.run)

    improved_plan: Optional[PlanList] = None
    improved_value: Optional[float] = None

    seed = 0
    while time.time() < deadline:
        plan, raw_value = _run_single_seed(
            EurisScheduler,
            eur_instance,
            seed,
            constructor_sig,
            run_sig,
            dataset_path,
        )
        if plan:
            candidate_value: Optional[float]
            if raw_value is None or not isinstance(raw_value, (int, float)) or not math.isfinite(raw_value):
                candidate_value = _compute_kpi(data, plan, objective_norm)
            else:
                candidate_value = float(raw_value)
            if candidate_value is not None and math.isfinite(candidate_value):
                if baseline_value is not None and math.isfinite(baseline_value):
                    delta = baseline_value - candidate_value
                    pct = (delta / baseline_value * 100.0) if baseline_value else 0.0
                    print(
                        f"[heuristic] seed={seed} valore={candidate_value:.6f} "
                        f"baseline={baseline_value:.6f} delta={delta:.6f} ({pct:+.3f}%)"
                    )
                    if delta > 1e-9:
                        improved_plan = plan
                        improved_value = candidate_value
                        print("[heuristic] miglioramento trovato, termino.")
                        break
                else:
                    improved_plan = plan
                    improved_value = candidate_value
                    print(f"[heuristic] seed={seed} valore={candidate_value:.6f} (prima soluzione valida).")
                    break
        seed += 1

    if improved_plan is not None and improved_value is not None:
        print(f"[heuristic] soluzione euristica salvata con valore {improved_value:.6f}.")
        _write_solution(output_file, objective_norm, improved_plan, improved_value, slot_minutes)
        return str(output_file)

    if baseline_plan:
        fallback_value = baseline_value if baseline_value is not None else float("nan")
        print("[heuristic] nessun miglioramento entro il limite: ripristino baseline.")
        _write_solution(output_file, objective_norm, baseline_plan, float(fallback_value), slot_minutes)
        return str(output_file)

    print("[heuristic] nessuna soluzione valida: piano vuoto.")
    _write_solution(output_file, objective_norm, [], float("nan"), slot_minutes)
    return str(output_file)
