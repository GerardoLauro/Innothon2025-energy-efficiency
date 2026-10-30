from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve()
PACKAGE_ROOT = HERE.parent
REPO_ROOT = PACKAGE_ROOT.parent

from EnergyBot5.optimization.optimizer_core import load_instance


BASELINE_ALIASES = (
    "initial_plan",
    "baseline_plan",
    "initial_schedule",
    "baseline",
    "schedule",
)

PlanEntry = Dict[str, int]
PlanList = List[PlanEntry]


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


def _plan_from_instance(instance_path: Path) -> PlanList:
    payload = _read_json_dict(instance_path)
    if not isinstance(payload, dict):
        return []
    for alias in BASELINE_ALIASES:
        if alias in payload:
            plan = _plan_from_container(payload[alias])
            if plan:
                return plan
    return []


def _plan_from_file(path: Path) -> PlanList:
    payload = _read_json_dict(path)
    if not isinstance(payload, dict):
        return []
    return _plan_from_container(payload)


def _write_plan(path: Path, plan: PlanList) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"plan": plan}, indent=2), encoding="utf-8")


def _build_naive_baseline(data: Dict[str, Any]) -> PlanList:
    slots = int(data["slots"])
    workforce = [float(x) for x in data["workforce"]]
    machines = {mid: [False] * slots for mid in data.get("machines_power", {})}
    durations = {act["id"]: int(act["dur"]) for act in data["activities"]}
    employees = {act["id"]: float(act.get("employees", 0.0)) for act in data["activities"]}
    machine_req = {act["id"]: act.get("machine") for act in data["activities"]}
    earliest = {act["id"]: int(act["earliest"]) for act in data["activities"]}
    latest = {act["id"]: int(act["latest"]) for act in data["activities"]}

    preds_map: Dict[str, List[str]] = {}
    for pred, succ in data.get("precedences", []):
        preds_map.setdefault(succ, []).append(pred)

    schedule: Dict[str, int] = {}
    load_emp = [0.0] * slots
    plan: PlanList = []

    sorted_activities = sorted(
        (act["id"] for act in data["activities"]),
        key=lambda aid: (earliest[aid], aid),
    )

    for aid in sorted_activities:
        dur = durations[aid]
        req_emp = employees[aid]
        req_machine = machine_req.get(aid)
        start_window = range(earliest[aid], latest[aid] + 1)
        preds = preds_map.get(aid, [])

        start_chosen: Optional[int] = None
        for start in start_window:
            end = start + dur
            if end > slots:
                continue
            feasible = True

            # Workforce check
            for t in range(start, end):
                if load_emp[t] + req_emp > workforce[t] + 1e-9:
                    feasible = False
                    break
            if not feasible:
                continue

            # Machine availability
            if req_machine:
                machine_usage = machines.setdefault(req_machine, [False] * slots)
                if any(machine_usage[t] for t in range(start, end)):
                    continue

            # Precedence constraints
            for pred in preds:
                if pred not in schedule:
                    feasible = False
                    break
                if start < schedule[pred] + durations[pred]:
                    feasible = False
                    break
            if not feasible:
                continue

            start_chosen = start
            break

        if start_chosen is None:
            continue

        end_slot = start_chosen + dur
        for t in range(start_chosen, end_slot):
            load_emp[t] += req_emp
            if req_machine:
                machines.setdefault(req_machine, [False] * slots)[t] = True
        schedule[aid] = start_chosen
        plan.append(
            {
                "activity": aid,
                "start_slot": start_chosen,
                "end_slot": end_slot,
            }
        )

    return sorted(plan, key=lambda item: (item["start_slot"], item["activity"]))


def _hhmm(slot: int, slot_minutes: int) -> str:
    total = slot * slot_minutes
    hours, minutes = divmod(total, 60)
    return f"{int(hours):02d}:{int(minutes):02d}"


def _plan_load(data: Dict[str, Any], plan: PlanList) -> List[float]:
    slots = int(data["slots"])
    load = [0.0] * slots
    power = {a["id"]: float(a.get("power_kw", 0.0)) for a in data["activities"]}
    for entry in plan:
        start = max(0, min(slots, int(entry["start_slot"])))
        end = max(start, min(slots, int(entry["end_slot"])))
        power_kw = power.get(entry["activity"], 0.0)
        if power_kw == 0.0:
            continue
        for t in range(start, end):
            load[t] += power_kw
    return load


def _kpi(data: Dict[str, Any], plan: PlanList, objective: str) -> Tuple[Optional[float], str]:
    if not plan:
        return None, "EUR" if objective == "min_cost" else "kW"
    load = _plan_load(data, plan)
    if objective == "min_cost":
        slot_hours = float(data.get("slot_hours", 1.0))
        prices = [float(p) for p in data.get("pricing", [])]
        if not prices:
            return None, "EUR"
        total = 0.0
        for idx, kw in enumerate(load):
            price = prices[idx] if idx < len(prices) else prices[-1]
            total += price * kw * slot_hours
        return total, "EUR"
    return (max(load) if load else 0.0), "kW"


def _render_table(plan: PlanList, slot_minutes: int) -> str:
    header = "ATTIVITÀ|INIZIO|FINE"
    if not plan:
        return header + "\n(nessuna attività)"
    lines = [header]
    for entry in sorted(plan, key=lambda item: (item["start_slot"], item["activity"])):
        lines.append(
            f"{entry['activity']}|{_hhmm(entry['start_slot'], slot_minutes)}|{_hhmm(entry['end_slot'], slot_minutes)}"
        )
    return "\n".join(lines)


def _resolve_baseline_plan(
    instance_path: Path,
    baseline_path: Path,
    data: Dict[str, Any],
) -> PlanList:
    plan_from_instance = _plan_from_instance(instance_path)
    if plan_from_instance:
        try:
            _write_plan(baseline_path, plan_from_instance)
        except Exception:
            pass
        return plan_from_instance

    if baseline_path.exists():
        plan_from_file = _plan_from_file(baseline_path)
        if plan_from_file:
            return plan_from_file

    naive_plan = _build_naive_baseline(data)
    try:
        _write_plan(baseline_path, naive_plan)
    except Exception:
        pass
    return naive_plan


def generate(instance_path: str, solution_path: str, baseline_path: str, export_path: str) -> None:
    instance_file = Path(instance_path).resolve()
    solution_file = Path(solution_path).resolve()
    baseline_file = Path(baseline_path).resolve()
    export_file = Path(export_path).resolve()

    if not instance_file.is_file():
        raise FileNotFoundError(f"Istanza non trovata: {instance_file}")
    if not solution_file.is_file():
        raise FileNotFoundError(f"Soluzione non trovata: {solution_file}")
    data = load_instance(str(instance_file))
    solution_data = _read_json_dict(solution_file) or {}
    plan_opt = _plan_from_container(solution_data) if solution_data else []

    objective = str(solution_data.get("objective", data.get("objective", "min_cost"))).lower()
    if objective not in ("min_cost", "min_peak"):
        objective = "min_cost"

    baseline_plan = _resolve_baseline_plan(instance_file, baseline_file, data)
    slot_minutes = int(data["slot_minutes"])

    table_opt = _render_table(plan_opt, slot_minutes)
    table_baseline = _render_table(baseline_plan, slot_minutes)

    v_opt, unit = _kpi(data, plan_opt, objective)
    v_base, _ = _kpi(data, baseline_plan, objective)

    delta = None
    pct = None
    if v_opt is not None and v_base is not None:
        delta = v_base - v_opt
        pct = (delta / v_base * 100.0) if v_base else None

    unit_label = "€" if unit == "EUR" else unit

    print("\n=== Piano ottimizzato ===")
    print(table_opt)
    print("\n=== Piano baseline ===")
    print(table_baseline)

    print("\n=== KPI ===")
    if v_opt is None:
        print(f"- Ottimizzato: n/d {unit_label}")
    else:
        print(f"- Ottimizzato: {v_opt:.2f} {unit_label}")
    if v_base is None:
        print(f"- Baseline:   n/d {unit_label}")
    else:
        print(f"- Baseline:   {v_base:.2f} {unit_label}")
    if delta is not None:
        print(f"- Risparmio:  {delta:+.2f} {unit_label}")
    if pct is not None:
        print(f"- Variazione: {pct:+.2f}%")

    lines = [
        "# Energy Planner - Report",
        f"_Generated: {datetime.now():%Y-%m-%d %H:%M:%S}_",
        "",
        f"**Objective:** {'Minimize Cost (€)' if objective == 'min_cost' else 'Minimize Peak (kW)'}",
        "",
        "## Piano ottimizzato",
        "```",
        table_opt,
        "```",
        "",
        "## Piano baseline",
        "```",
        table_baseline,
        "```",
        "",
        "## KPI",
    ]

    if v_opt is None:
        lines.append(f"- Ottimizzato: n/d {unit_label}")
    else:
        lines.append(f"- Ottimizzato: {v_opt:.2f} {unit_label}")
    if v_base is None:
        lines.append(f"- Baseline:   n/d {unit_label}")
    else:
        lines.append(f"- Baseline:   {v_base:.2f} {unit_label}")
    if delta is not None:
        lines.append(f"- Risparmio:  {delta:+.2f} {unit_label}")
    if pct is not None:
        lines.append(f"- Variazione: {pct:+.2f}%")

    export_file.parent.mkdir(parents=True, exist_ok=True)
    export_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Report scritto: {export_file}")


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Genera il report da istanza e soluzione JSON")
    parser.add_argument("--instance", default="out/instance.json")
    parser.add_argument("--solution", default="out/solution.json")
    parser.add_argument("--baseline", default="out/baseline.json")
    parser.add_argument("--export", default="out/report.md")
    parser.add_argument("--objective", choices=["cost", "peak"], help="Compatibilita; l'obiettivo effettivo e nella soluzione")
    args = parser.parse_args(argv)
    generate(args.instance, args.solution, args.baseline, args.export)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
