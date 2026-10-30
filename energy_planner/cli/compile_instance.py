from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

from energy_planner.instance.merge_prices import inject_prices
from energy_planner.pricing.forecaster_adapter import ForecasterClient


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _deep_copy(data: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(data))


def _extract_instance(data: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("compiled_instance", "instance"):
        if isinstance(data.get(key), dict):
            return data[key]
    return data


def _extract_pricing(data: Dict[str, Any], instance: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    candidates = []
    if isinstance(instance.get("pricing"), dict):
        candidates.append(instance["pricing"])
    elif isinstance(instance.get("pricing"), list):
        candidates.append({"per_slot": instance["pricing"]})

    if isinstance(data.get("pricing"), dict):
        candidates.append(data["pricing"])

    for candidate in candidates:
        per_hour = candidate.get("per_hour") if isinstance(candidate, dict) else None
        per_slot = candidate.get("per_slot") if isinstance(candidate, dict) else None
        if per_hour or per_slot:
            return candidate
    return None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compila l'istanza finale garantendo prezzi a 5 minuti.")
    parser.add_argument("--session-json", required=True, help="Percorso JSON generato dalla conversazione.")
    parser.add_argument("--city", required=True, help="Città per il recupero prezzi se mancanti.")
    parser.add_argument("--hours", type=int, help="Orizzonte orario; default derivato dall'istanza o 24.")
    parser.add_argument("--out", required=True, help="Percorso di output per instance_enriched.json.")
    args = parser.parse_args(argv)

    if args.hours is not None and args.hours <= 0:
        parser.error("--hours deve essere maggiore di zero")

    session_path = Path(args.session_json).expanduser()
    out_path = Path(args.out).expanduser()

    session_data = _load_json(session_path)
    instance = _deep_copy(_extract_instance(session_data))
    time_data = instance.get("time", {})
    slots = int(time_data.get("slots", 0))
    if int(time_data.get("slot_minutes", 5)) != 5:
        parser.error("L'integrazione prezzi richiede slot da 5 minuti")
    hours = args.hours or ((slots + 11) // 12 if slots > 0 else 24)

    pricing = _extract_pricing(session_data, instance)
    if pricing is None:
        client = ForecasterClient()
        forecast = client.predict_hourly(args.city, hours=hours)
        pricing = {"per_hour": forecast.get("per_hour", [])}

    enriched = inject_prices(instance, pricing, to_per_slot=True)
    if slots:
        if len(enriched["pricing"]) < slots:
            raise ValueError("Serie prezzi piu corta dell'orizzonte dell'istanza")
        enriched["pricing"] = enriched["pricing"][:slots]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(enriched, handle, indent=2, ensure_ascii=False)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
