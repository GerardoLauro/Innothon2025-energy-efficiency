from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

from energy_planner.pricing.forecaster_adapter import (
    ForecasterClient,
    expand_per_hour_to_per_slot,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ottieni prezzi orari (e a slot) dal Price Forecaster."
    )
    parser.add_argument(
        "--city",
        required=True,
        help="Città supportata: Milano, Roma, Napoli.",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Numero di ore da prevedere (default: 24).",
    )
    parser.add_argument(
        "--per-slot",
        action="store_true",
        help="Espandi i prezzi orari in slot da 5 minuti.",
    )
    parser.add_argument(
        "--out",
        type=str,
        help="Percorso file per salvare il risultato in JSON.",
    )
    return parser


def _build_output(payload: Dict[str, Any], include_slots: bool) -> Dict[str, Any]:
    result = {
        "city": payload.get("city"),
        "start": payload.get("start"),
        "per_hour": payload.get("per_hour", []),
        "meta": payload.get("meta", {}),
    }

    if include_slots:
        per_hour = result["per_hour"]
        result["per_slot"] = expand_per_hour_to_per_slot(per_hour)
    return result


def _write_output(target: Path, content: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2, ensure_ascii=True)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.hours <= 0:
        parser.error("--hours deve essere maggiore di zero.")

    client = ForecasterClient()
    silent_buffer = io.StringIO()
    with contextlib.redirect_stdout(silent_buffer):
        payload = client.predict_hourly(args.city, args.hours)
    result = _build_output(payload, args.per_slot)

    meta_obj = result.get("meta")
    meta = meta_obj if isinstance(meta_obj, dict) else {}
    source = meta.get("source")
    if source != "Price_forecaster":
        logging.warning("Prezzi non derivati dal forecaster: source=%s", source)

    if args.out:
        out_path = Path(args.out).expanduser()
        _write_output(out_path, result)
        print(f"Scritto {out_path}", file=sys.stderr)

    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
