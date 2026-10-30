#!/usr/bin/env python3
"""Launch using the local environment. Setup is an explicit separate step."""
from pathlib import Path
import subprocess
import sys

def main(args=None):
    root = Path(__file__).resolve().parent
    candidates = [root / ".venv/Scripts/python.exe", root / ".venv/bin/python"]
    python = next((str(p) for p in candidates if p.is_file()), sys.executable)
    check = subprocess.run([python, "-c", "import dotenv, pulp, numpy, requests, joblib"],
                           capture_output=True, text=True)
    if check.returncode:
        print("Dipendenze mancanti. Esegui scripts/setup.ps1 (Windows) oppure bash scripts/setup.sh.", file=sys.stderr)
        return 1
    return subprocess.call([python, "-m", "energy_planner", *(sys.argv[1:] if args is None else args)], cwd=root)

if __name__ == "__main__":
    raise SystemExit(main())
