"""Compatibility launcher; use python -m energy_planner."""
from energy_planner.cli.app import main

if __name__ == "__main__":
    raise SystemExit(main())
