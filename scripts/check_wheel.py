#!/usr/bin/env python3
"""Check the built wheel in an isolated directory, without reinstalling dependencies."""
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    distribution_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "dist"
    wheels = sorted(distribution_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Build exactly one wheel in dist/ before running this check")
    with tempfile.TemporaryDirectory(prefix="energy-planner-wheel-") as temporary:
        target = Path(temporary) / "installed"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-compile",
                        "--target", str(target), str(wheels[0])], check=True)
        code = """
import pathlib, sys
target = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(target))
import energy_planner
assert pathlib.Path(energy_planner.__file__).resolve().is_relative_to(target)
from energy_planner.prompts.loader import load_system_prompt, load_few_shots
assert load_system_prompt() and load_few_shots()
from energy_planner.cli.app import main
raise SystemExit(main(['demo', '--output-dir', 'demo']))
"""
        subprocess.run([sys.executable, "-I", "-X", "utf8", "-c", code, str(target)],
                       check=True, cwd=temporary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
