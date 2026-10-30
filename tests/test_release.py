"""Regression coverage for the publication and integration fixes."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from energy_planner.cli.app import main
from energy_planner.core.triple_store import Triple, TripleStore
from energy_planner.core.compiler import compile_instance
from energy_planner.instance.merge_prices import inject_prices
from energy_planner.llm.provider import MockProvider
from energy_planner.prompts.loader import load_system_prompt, load_few_shots


def test_packaged_prompts_load_outside_repository():
    assert load_system_prompt()
    assert load_few_shots()


def test_importing_forecaster_does_not_start_training(repository_root):
    source = repository_root / "price_forecaster/code/Price_forecaster.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for statement in tree.body:
        # run() must only appear inside the explicit __main__ guard.
        if isinstance(statement, (ast.Assign, ast.Expr)):
            assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                           and n.func.id == "run" for n in ast.walk(statement))


def test_forecaster_construction_is_lazy(monkeypatch):
    from energy_planner.pricing.forecaster_adapter import ForecasterClient

    def forbid_import(*args):
        raise AssertionError("Construction must not import optional ML dependencies")

    monkeypatch.setattr(ForecasterClient, "_load_module_once", forbid_import)
    ForecasterClient(cache_ttl_minutes=0)


@pytest.mark.parametrize("objective", ["cost", "peak"])
@pytest.mark.smoke
def test_offline_demo_runs_solver_and_report(tmp_path, objective):
    target = tmp_path / objective
    assert main(["demo", "--output-dir", str(target), "--objective", objective]) == 0
    result = json.loads((target / "solution.json").read_text())
    assert result["solver"] == "PuLP"  # The demo must exercise CBC, not quietly fall back.
    assert result["objective"] == {"cost": "min_cost", "peak": "min_peak"}[objective]
    assert {row["activity"] for row in result["plan"]} == {"demo_A", "demo_B"}
    assert (target / "report.md").is_file()


def test_enriched_instance_is_consumable_by_solver(tmp_path):
    from EnergyBot5.optimization.optimizer_core import load_instance
    store = TripleStore()
    store.ingest([Triple("horizon", "hours", 1)])
    instance = inject_prices(compile_instance(store), {"per_hour": [0.25]})
    target = tmp_path / "instance.json"
    target.write_text(json.dumps(instance), encoding="utf-8")
    loaded = load_instance(str(target))
    assert loaded["pricing"] == [0.25] * 12


def test_mock_provider_is_finite_and_supports_streaming():
    provider = MockProvider(responses=["first", "second"])
    assert provider.complete([]) == "first"
    assert list(provider.complete([], stream=True)) == ["second"]
    with pytest.raises(RuntimeError, match="esaurite"):
        provider.complete([])


def test_mock_chat_smoke(tmp_path, monkeypatch):
    answers = tmp_path / "mock.json"
    answers.write_text(json.dumps(["In quale citta vuoi pianificare?"]), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda *args: ":quit")
    assert main(["chat", "--provider", "mock", "--mock-responses", str(answers)]) == 0


def test_no_automatic_pip_or_solver_download_on_import(tmp_path):
    code = """
import subprocess, socket
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected external operation during import')
subprocess.run = forbidden
socket.socket.connect = forbidden
import EnergyBot5.__main__
import EnergyBot5.install_solver
import energy_planner.cli.app
"""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    completed = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                               capture_output=True, text=True, env=env)
    assert completed.returncode == 0, completed.stderr
    assert list(tmp_path.iterdir()) == []


def test_cli_rejects_unsupported_city():
    assert main(["prices", "paste", "--city", "../../unsafe", "--values", "0.25," * 23 + "0.25"]) == 1


def test_report_requires_existing_solution(tmp_path):
    from EnergyBot5.reporting.schedule_report import generate
    source = tmp_path / "instance.json"
    source.write_text("{}")
    with pytest.raises(FileNotFoundError, match="Soluzione"):
        generate(str(source), str(tmp_path / "missing.json"), str(tmp_path / "baseline.json"),
                 str(tmp_path / "report.md"))


def test_compile_command_keeps_canonical_pricing_format(tmp_path, repository_root):
    from energy_planner.cli.compile_instance import main as compile_cli
    from EnergyBot5.optimization.optimizer_core import load_instance
    output = tmp_path / "enriched.json"
    assert compile_cli(["--session-json", str(repository_root / "data/examples/demo_instance.json"),
                        "--city", "Milano", "--out", str(output)]) == 0
    assert len(load_instance(str(output))["pricing"]) == 12


@pytest.mark.parametrize("module", ["EnergyBot5.optimization.minimizzazione_costo",
                                   "EnergyBot5.optimization.minimizzazione_picco"])
def test_legacy_optimization_commands(module, tmp_path, repository_root):
    output = tmp_path / "solution.json"
    result = subprocess.run([sys.executable, "-X", "utf8", "-m", module,
                             "--input", str(repository_root / "data/examples/demo_instance.json"),
                             "--output", str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(output.read_text())["plan"]) == 2


def test_heuristic_fallback_can_run_without_private_assets(tmp_path, repository_root):
    from EnergyBot5.optimization.heuristic_fallback import run_heuristic_until_better
    output = tmp_path / "heuristic.json"
    run_heuristic_until_better(str(repository_root / "data/examples/demo_instance.json"),
                               str(output), "min_cost", wallclock_sec=1)
    assert len(json.loads(output.read_text())["plan"]) == 2
