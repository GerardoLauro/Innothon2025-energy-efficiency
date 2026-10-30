"""Offline integration demo using explicit synthetic data."""
import json
from pathlib import Path
from importlib.resources import files

def run_demo(output_dir: Path, objective: str = "cost") -> dict:
    from EnergyBot5.optimization.optimizer_core import solve_instance
    from EnergyBot5.reporting.schedule_report import generate
    output_dir.mkdir(parents=True, exist_ok=True)
    instance = json.loads(files("energy_planner").joinpath("resources/demo_instance.json").read_text(encoding="utf-8"))
    instance["objective"] = "min_peak" if objective == "peak" else "min_cost"
    instance_path = output_dir / "instance.json"
    solution_path = output_dir / "solution.json"
    baseline_path = output_dir / "baseline.json"
    report_path = output_dir / "report.md"
    instance_path.write_text(json.dumps(instance, indent=2), encoding="utf-8")
    # Baseline must belong to this invocation and selected objective.
    if baseline_path.exists():
        baseline_path.unlink()
    solve_instance(str(instance_path), str(solution_path), instance["objective"])
    generate(str(instance_path), str(solution_path), str(baseline_path), str(report_path))
    print(f"Demo con dati sintetici completata: {output_dir.resolve()}")
    return json.loads(solution_path.read_text(encoding="utf-8"))
