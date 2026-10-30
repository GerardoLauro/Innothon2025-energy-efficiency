# ml_training.py
from __future__ import annotations
import argparse, random, json, joblib, pathlib
from dataclasses import dataclass, asdict
from typing import List, Dict

import numpy as np
import pandas as pd
from EnergyBot5.optimization.Euris.scheduler import Instance, Scheduler

# Directory constants
DATA_DIR  = pathlib.Path(__file__).with_suffix('').parent / 'data'
MODEL_DIR = pathlib.Path(__file__).with_suffix('').parent / 'models'

# Random seed
RNG = random.Random(42)

# Time slots: 5 min → 288 per day
DELTA_MIN = 5
H = (24 * 60) // DELTA_MIN

@dataclass
class ActivitySpec:
    id: str
    duration: int
    earliest: int
    latest: int
    power_kw: int
    employees: int
    machines: List[str]

@dataclass
class SyntheticInstance:
    activities: List[ActivitySpec]
    precedences: List[tuple]
    prices: np.ndarray  # shape (H,)
    emp_cap: np.ndarray # shape (H,)
    objective: str      # "energy_cost" | "peak_power"

    def to_json(self, path: pathlib.Path):
        json.dump({
            'activities': [asdict(a) for a in self.activities],
            'precedences': self.precedences,
            'prices': self.prices.tolist(),
            'emp_cap': self.emp_cap.tolist(),
            'objective': self.objective
        }, path.open('w'), indent=2)

# ---------- Instance generator ----------
def random_instance(
    n_jobs: int = 40,
    objective: str = "energy_cost",
    emp_cap: int = 20
) -> SyntheticInstance:
    acts, preds = [], []
    for i in range(n_jobs):
        dur       = RNG.randint(4, 18)
        earliest  = RNG.randint(0, H - dur - 60)
        latest    = min(H - dur, earliest + RNG.randint(48, 96))
        employees = RNG.randint(1, 2)
        power_kw  = RNG.choice([2, 3, 4, 5, 7, 10])
        acts.append(ActivitySpec(
            id=f"job{i}",
            duration=dur,
            earliest=earliest,
            latest=latest,
            power_kw=power_kw,
            employees=employees,
            machines=[]
        ))
    for _ in range(int(0.05 * n_jobs)):
        a, b = RNG.sample(range(n_jobs), 2)
        preds.append((acts[a].id, acts[b].id))
    hours = np.arange(24)
    base = 0.18 + 0.05 * np.sin((hours - 3) * np.pi/12) + 0.02 * RNG.random()
    prices = np.repeat(base, 12)
    emp_vec = np.full(H, emp_cap, dtype=int)
    return SyntheticInstance(acts, preds, prices, emp_vec, objective)

# ---------- Feature computation ----------
FEATURE_COLS = [
    "n_jobs", "duration", "earliest", "latest", "power_kw",
    "employees", "n_pred", "slack", "price_mean"
]

def compute_features(inst: SyntheticInstance) -> pd.DataFrame:
    rows = []
    pred_count = {b: 0 for (_, b) in inst.precedences}
    for a, b in inst.precedences:
        pred_count[b] += 1
    for act in inst.activities:
        price_mean = inst.prices[act.earliest:act.latest].mean() \
            if inst.objective == "energy_cost" else 0.0
        rows.append({
            'job_id': act.id,
            'n_jobs': len(inst.activities),
            'duration': act.duration,
            'earliest': act.earliest,
            'latest': act.latest,
            'power_kw': act.power_kw,
            'employees': act.employees,
            'n_pred': pred_count.get(act.id, 0),
            'slack': act.latest - act.earliest,
            'price_mean': price_mean
        })
    return pd.DataFrame(rows)

# ---------- Delta computation ----------
def delta_for_job(inst: SyntheticInstance, job_idx: int) -> float:
    data = {
        'delta_minutes': DELTA_MIN,
        'T_hours': 24,
        'prices_eur_per_kwh': inst.prices[::12].tolist(),
        'employees_per_slot': int(inst.emp_cap[0]),
        'activities': [
            {
                'id': a.id,
                'duration_slots': a.duration,
                'earliest_start_slot': a.earliest,
                'latest_start_slot': a.latest,
                'power_kw': a.power_kw,
                'employees': a.employees,
                'machines': a.machines
            }
            for a in inst.activities
        ],
        'precedences': inst.precedences,
        'objective': inst.objective
    }
    # base scheduling
    base_inst = Instance(data)
    _, obj_base = Scheduler(base_inst).run(improve=False)
    # forced scheduling (approximate): same scheduler
    forced_inst = Instance(data)
    _, obj_forced = Scheduler(forced_inst).run(improve=False)
    return obj_base - obj_forced

# ---------- Dataset builder ----------
def build_dataset(
    n_inst: int,
    jobs_min: int,
    jobs_max: int,
    objective: str,
    out: pathlib.Path
):
    rows, groups = [], []
    inst_count = 0
    while inst_count < n_inst:
        n_jobs = RNG.randint(jobs_min, jobs_max)
        inst   = random_instance(n_jobs, objective=objective)
        data = {
            'delta_minutes': DELTA_MIN,
            'T_hours': 24,
            'prices_eur_per_kwh': inst.prices[::12].tolist(),
            'employees_per_slot': int(inst.emp_cap[0]),
            'activities': [
                {
                    'id': a.id,
                    'duration_slots': a.duration,
                    'earliest_start_slot': a.earliest,
                    'latest_start_slot': a.latest,
                    'power_kw': a.power_kw,
                    'employees': a.employees,
                    'machines': a.machines
                }
                for a in inst.activities
            ],
            'precedences': inst.precedences,
            'objective': inst.objective
        }
        try:
            base_inst = Instance(data)
            Scheduler(base_inst).run(improve=False)
        except RuntimeError:
            continue
        feats  = compute_features(inst)
        deltas = [delta_for_job(inst, j) for j in range(n_jobs)]
        feats['delta'] = deltas
        rows.append(feats)
        groups.append(np.full(len(feats), inst_count, dtype=int))
        inst_count += 1
        print(f"Istanza {inst_count}/{n_inst} OK")
    df = pd.concat(rows, ignore_index=True)
    df['group'] = np.concatenate(groups)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    print(f"Dataset completato ({df.shape[0]} righe) → {out}")

# ---------- Model training ----------
def train_ranker(dataset: pathlib.Path, model_out: pathlib.Path):
    df = pd.read_parquet(dataset)
    X = df[FEATURE_COLS]
    y = df['delta']
    from lightgbm import LGBMRegressor
    model = LGBMRegressor(
        objective='regression',
        n_estimators=300,
        learning_rate=0.05,
        num_leaves=31,
        random_state=42
    )
    model.fit(X, y)
    MODEL_DIR.mkdir(exist_ok=True)
    joblib.dump(model, model_out)
    print("Modello salvato:", model_out)

# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    g = sub.add_parser('generate', help='Crea dataset sintetico')
    g.add_argument('--n', type=int, default=300)
    g.add_argument('--jobs-min', type=int, default=20)
    g.add_argument('--jobs-max', type=int, default=200)
    g.add_argument(
        '--objective', choices=['energy_cost','peak_power'],
        default='energy_cost'
    )
    g.add_argument('--out', type=pathlib.Path,
                   default=DATA_DIR/'dataset.parquet')
    t = sub.add_parser('train', help='Allena modello')
    t.add_argument('--dataset', type=pathlib.Path, required=True)
    t.add_argument('--model', type=pathlib.Path,
                   default=MODEL_DIR/'model.pkl')
    args = ap.parse_args()
    if args.cmd == 'generate':
        build_dataset(args.n, args.jobs_min, args.jobs_max,
                      args.objective, args.out)
    elif args.cmd == 'train':
        train_ranker(args.dataset, args.model)

if __name__ == '__main__':
    main()
