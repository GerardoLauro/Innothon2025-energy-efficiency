from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from EnergyBot5.optimization.optimizer_core import solve_instance


def main():
    ap = argparse.ArgumentParser(description="Minimizzazione costo – da instance.json a solution.json")
    root = Path.cwd()
    ap.add_argument("--input", "-i", default=str(root / "out" / "instance.json"))
    ap.add_argument("--output", "-o", default=str(root / "out" / "solution.json"))
    args = ap.parse_args()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out = solve_instance(args.input, args.output, "min_cost")
    print(f"[OK] Costo: soluzione in {out}")


if __name__ == "__main__":
    main()
