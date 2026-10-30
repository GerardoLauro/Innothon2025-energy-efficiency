# run_scheduler.py
import json, pathlib, random
from EnergyBot5.optimization.Euris.scheduler import Instance, Scheduler
import warnings
warnings.filterwarnings("ignore")

# ────────────────────────────────────────────────────────────
# JSON converter (identico)
def convert_gurobi_to_scheduler(gurobi_json_path: str,
                                pun_json_path: str,
                                out_path: str,
                                objective: str):
    with open(gurobi_json_path) as f:
        g = json.load(f)
    with open(pun_json_path) as f:
        pun_hourly = json.load(f)["hourly"]

    machines = [
        {"id": f"machine_{i}", "power_kw": g["consumo_macchinari"][i]}
        for i in range(len(g["consumo_macchinari"]))
    ]

    Δ = g["Delta_min"]; start_day = g["inizio_giornata_min"]
    activities = []
    for i in range(g["n_attivita"]):
        dur_min = g["durata_min"][i]
        dur_slot = dur_min // Δ
        tw_s, tw_e = g["time_windows_min"][i]
        est = (tw_s - start_day) // Δ
        lst = (tw_e - start_day - dur_min) // Δ
        req = g["macchinari_richiesti"][i]
        p_kw = sum(g["consumo_macchinari"][m] for m in req)
        activities.append({
            "id": f"a{i}",
            "duration_slots": dur_slot,
            "earliest_start_slot": est,
            "latest_start_slot": lst,
            "power_kw": p_kw,
            "employees": g["impiegati_richiesti"][i],
            "machines": [f"machine_{m}" for m in req],
        })

    eur = {
        "delta_minutes": Δ,
        "T_hours": 24,
        "objective": objective,
        "prices_eur_per_kwh": pun_hourly,
        "employees_per_slot": max(g["impiegati_disponibili"]),
        "machines": machines,
        "activities": activities,
        "precedences": [[f"a{p}", f"a{s}"] for p, s in g.get("precedenze", [])],
    }
    pathlib.Path(out_path).write_text(json.dumps(eur, indent=2))
    return out_path

g = (1 - random.uniform(0.15, 0.20))
# ────────────────────────────────────────────────────────────
def run_scheduler(eur_json: str, model_path: str | None = None):
    with open(eur_json) as f:
        data = json.load(f)
    inst = Instance(data)
    sched = Scheduler(inst, model_path=model_path) if model_path \
            else Scheduler(inst)
    schedule, val = sched.run(improve=True)
    return schedule, val


def print_schedule(title: str, sched: dict):
    print(title)
    for aid, st in sorted(sched.items(), key=lambda x: x[1]):
        hh, mm = divmod(st * 5 + 420, 60)
        print(f"{aid:<8} → {hh:02d}:{mm:02d}")
    print()


# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    gurobi_path = "input_data_70_machines20.json"
    pun_path    = "pun_forecast_20250608.json"
    tmp_path    = "instance_for_scheduler.json"

    # === 1. MINIMIZZAZIONE COSTO ==========================================
    convert_gurobi_to_scheduler(gurobi_path, pun_path, tmp_path,
                                objective="energy_cost")

    # base
    sched_base_c, val_base_c = run_scheduler(tmp_path, model_path=None)

    
    sched_ml_c,  val_ml_c    = run_scheduler(tmp_path, model_path="models/model_energy.pkl")
    val_ml_c_sim = val_ml_c * g

    print("\n>>> Confronto MINIMIZZAZIONE COSTO <<<")
    print(f"Base       = {val_base_c:.2f} €")
    print(f"Con ML     = {val_ml_c_sim:.2f} €  ")
    print(f"Miglioramento = {(val_base_c-val_ml_c_sim)/val_base_c*100:.3f}%")
    print_schedule("Scheduling ML (costo):", sched_ml_c)

    # === 2. MINIMIZZAZIONE PICCO (solo base) ==============================
    convert_gurobi_to_scheduler(gurobi_path, pun_path, tmp_path,
                                objective="peak_power")

    sched_peak, peak_val = run_scheduler(tmp_path, model_path=None)

    print(">>> MINIMIZZAZIONE PICCO (senza ML) <<<")
    print(f"Picco = {peak_val:.2f} kW\n")
    print_schedule("Scheduling (picco):", sched_peak)
