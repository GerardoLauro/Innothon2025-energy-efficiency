"""Backward compatible --mode entry point."""
import argparse
from energy_planner.cli.app import main as cli

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Compatibilita EnergyBot5; preferire energy-planner")
    parser.add_argument("--mode", choices=["chat", "opt"], default="opt")
    parser.add_argument("--objective", choices=["cost", "peak"])
    parser.add_argument("--input", "-i", default="out/instance.json")
    parser.add_argument("--output", "-o", default="out/solution.json")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--baseline", default="out/baseline.json")
    parser.add_argument("--report-path", default="out/report.md")
    args = parser.parse_args(argv)
    if args.mode == "chat":
        status = cli(["chat"])
        if status:
            return status
    command = ["optimize", "--input", args.input, "--output", args.output]
    if args.objective:
        command.extend(["--objective", args.objective])
    if args.report:
        command.extend(["--report", "--baseline", args.baseline, "--report-path", args.report_path])
    return cli(command)

if __name__ == "__main__":
    raise SystemExit(main())
