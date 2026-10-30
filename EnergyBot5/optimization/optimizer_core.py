from __future__ import annotations
import json, re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pulp

from EnergyBot5.install_solver import ensure_cbc


def _norm_machine_id(mid: str | None) -> str | None:
    if mid is None:
        return None
    return mid.split(":", 1)[1] if ":" in mid else mid


def _parse_contract_power(assumptions: List[str] | None) -> float | None:
    if not assumptions:
        return None
    for s in assumptions:
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*kW", s, flags=re.I)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass
    return None


def load_instance(path: str) -> Dict[str, Any]:
    C = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    slot_minutes = int(C["time"]["slot_minutes"])
    slots = int(C["time"]["slots"])
    slot_hours = slot_minutes / 60.0

    pricing = C.get("pricing", [])
    if not isinstance(pricing, list) or len(pricing) != slots:
        raise ValueError(f"'pricing' deve essere una lista di lunghezza {slots}")

    wf = C.get("workforce", 1)
    if isinstance(wf, list):
        if len(wf) != slots:
            raise ValueError(f"'workforce' lista deve avere lunghezza {slots}")
        workforce = [float(x) for x in wf]
    elif isinstance(wf, (int, float)):
        workforce = [float(wf)] * slots
    else:
        raise ValueError("'workforce' deve essere list o numero")

    power_by_machine: Dict[str, float] = {}
    for m in C.get("machines", []):
        mid = _norm_machine_id(m["id"])
        pkw = float(m.get("power_kW", m.get("power_kw", 0.0)))
        power_by_machine[mid] = pkw

    activities = []
    for a in C.get("activities", []):
        aid = a["id"]
        dur = int(a["duration_slots"])
        window_slots = a.get("window_slots", [0, slots])
        w0 = int(window_slots[0]) if isinstance(window_slots, list) and window_slots else 0
        earliest = max(0, min(w0, max(0, slots - dur)))

        latest_candidate: Optional[int] = None
        latest_field = a.get("latest_start_slot")
        if latest_field is not None:
            try:
                latest_candidate = int(latest_field)
            except (TypeError, ValueError):
                latest_candidate = None

        if latest_candidate is None:
            if isinstance(window_slots, list) and len(window_slots) > 1:
                try:
                    latest_candidate = int(window_slots[1])
                except (TypeError, ValueError):
                    latest_candidate = None
        if latest_candidate is None:
            latest_candidate = earliest

        window_end_field = a.get("window_end_slot")
        if window_end_field is not None:
            try:
                end_slot = int(window_end_field)
                latest_candidate = min(latest_candidate, end_slot - dur)
            except (TypeError, ValueError):
                pass

        latest_candidate = max(earliest, latest_candidate)
        latest_candidate = min(latest_candidate, max(0, slots - dur))
        latest_start = latest_candidate
        emp = float(a.get("employees", 0.0))
        req_m = _norm_machine_id(a.get("requires_machine"))
        pkw = power_by_machine.get(req_m, 0.0) if req_m else 0.0
        activities.append({
            "id": aid,
            "dur": dur,
            "earliest": earliest,
            "latest": latest_start,
            "employees": emp,
            "machine": req_m,
            "power_kw": pkw,
        })

    precedences: List[Tuple[str, str]] = []
    for a in C.get("activities", []):
        succ = a["id"]
        for pred in a.get("precedences", []):
            precedences.append((pred, succ))

    locks = {lk["activity"]: int(lk["slot"]) for lk in C.get("locks", [])}

    contract_power_kw = C.get("contract_power_kw")
    if contract_power_kw is None:
        contract_power_kw = _parse_contract_power(C.get("assumptions"))

    obj = C.get("objective", "min_cost")
    return {
        "slot_minutes": slot_minutes,
        "slots": slots,
        "slot_hours": slot_hours,
        "pricing": [float(p) for p in pricing],
        "workforce": workforce,
        "machines_power": power_by_machine,
        "activities": activities,
        "precedences": precedences,
        "locks": locks,
        "contract_power_kw": float(contract_power_kw) if contract_power_kw is not None else None,
        "objective": obj,
    }


def build_model(data: Dict[str, Any], objective: str):
    A = [a["id"] for a in data["activities"]]
    T = list(range(data["slots"]))
    dur = {a["id"]: a["dur"] for a in data["activities"]}
    earliest = {a["id"]: a["earliest"] for a in data["activities"]}
    latest = {a["id"]: a["latest"] for a in data["activities"]}
    emp = {a["id"]: a["employees"] for a in data["activities"]}
    reqM = {a["id"]: a["machine"] for a in data["activities"]}
    powA = {a["id"]: a["power_kw"] for a in data["activities"]}

    price = data["pricing"]
    wf = data["workforce"]
    contract = data["contract_power_kw"]
    prob = pulp.LpProblem("energy_optimization", pulp.LpMinimize)

    start = {
        a: {t: pulp.LpVariable(f"start_{a}_{t}", 0, 1, cat="Binary") for t in T}
        for a in A
    }
    active = {
        a: {t: pulp.LpVariable(f"active_{a}_{t}", 0, 1, cat="Binary") for t in T}
        for a in A
    }

    # 1) one-start entro finestra
    for a in A:
        prob += pulp.lpSum(start[a][t] for t in range(earliest[a], latest[a] + 1)) == 1, f"one_start_{a}"

    # 2) link start->active
    for a in A:
        d = dur[a]
        for t in T:
            vs = [tau for tau in range(max(earliest[a], t - d + 1), min(t, latest[a]) + 1)]
            prob += (active[a][t] == (pulp.lpSum(start[a][tau] for tau in vs) if vs else 0)), f"active_{a}_{t}"

    # 3) workforce
    for t in T:
        prob += pulp.lpSum(emp[a] * active[a][t] for a in A) <= wf[t] + 1e-9, f"wf_{t}"

    # 4) macchina: no overlap
    machines = sorted(set(m for m in reqM.values() if m is not None))
    for m in machines:
        users = [a for a in A if reqM[a] == m]
        for t in T:
            prob += pulp.lpSum(active[a][t] for a in users) <= 1, f"m_{m}_{t}"

    # 5) locks
    for a, s in data["locks"].items():
        prob += start[a][s] == 1, f"lock_{a}"

    # 6) precedenze: end(pred) <= start(succ)
    for (p, s) in data["precedences"]:
        prob += (
            pulp.lpSum(tp * start[p][tp] for tp in range(earliest[p], latest[p] + 1))
            + dur[p]
            <= pulp.lpSum(ts * start[s][ts] for ts in range(earliest[s], latest[s] + 1))
        ), f"prec_{p}_{s}"

    # 7) potenza contrattuale
    if contract is not None:
        for t in T:
            prob += pulp.lpSum(powA[a] * active[a][t] for a in A) <= contract + 1e-9, f"contract_{t}"

    # Obiettivo
    if objective == "min_cost":
        slot_h = data["slot_hours"]
        prob += pulp.lpSum(price[t] * pulp.lpSum(powA[a] * active[a][t] for a in A) * slot_h for t in T)
    elif objective == "min_peak":
        P = pulp.LpVariable("P_peak", lowBound=0)
        for t in T:
            prob += pulp.lpSum(powA[a] * active[a][t] for a in A) <= P, f"peak_{t}"
        prob += P
    else:
        prob += 0
    return prob, start, data


def solve_instance(path_in: str, path_out: str, objective: str | None) -> str:
    data = load_instance(path_in)
    if objective not in ("min_cost", "min_peak"):
        objective = data.get("objective", "min_cost")
    prob, start, data = build_model(data, objective)

    cbc_path = None
    try:
        cbc_path = ensure_cbc()
    except Exception as exc:
        print(f"[WARN] CBC non disponibile: {exc}")

    status = "Not Solved"
    try:
        if cbc_path:
            solver = pulp.COIN_CMD(path=str(cbc_path), msg=False, timeLimit=30)
        else:
            solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=30)
        prob.solve(solver)
        status = pulp.LpStatus.get(prob.status, "Not Solved")
    except Exception as exc:
        status = "Error"
        print(f"[WARN] Errore durante la risoluzione con CBC: {exc}")

    if status != "Optimal":
        print("[WARN] CBC non ha trovato soluzione ottima entro 30s -> avvio euristica (30s)...")
        from EnergyBot5.optimization.heuristic_fallback import run_heuristic_until_better

        obj_name = objective if objective in ("min_cost", "min_peak") else data.get("objective", "min_cost")
        run_heuristic_until_better(path_in, path_out, obj_name, wallclock_sec=30)
        return path_out

    # Estrai piano
    slot_min = data["slot_minutes"]

    def hhmm(s):
        h = (s * slot_min) // 60
        m = (s * slot_min) % 60
        return f"{h:02d}:{m:02d}"

    plan = []
    for a in data["activities"]:
        aid = a["id"]
        s_found = None
        for t in range(a["earliest"], a["latest"] + 1):
            if pulp.value(start[aid][t]) > 0.5:
                s_found = t
                break
        if s_found is None:
            continue
        e = s_found + a["dur"]
        plan.append(
            {
                "activity": aid,
                "start_slot": int(s_found),
                "end_slot": int(e),
                "start_time": hhmm(s_found),
                "end_time": hhmm(e),
            }
        )

    out = {
        "solver": "PuLP",
        "objective": objective,
        "objective_value": float(pulp.value(prob.objective)),
        "plan": sorted(plan, key=lambda x: x["start_slot"]),
    }
    Path(path_out).parent.mkdir(parents=True, exist_ok=True)
    Path(path_out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return path_out
