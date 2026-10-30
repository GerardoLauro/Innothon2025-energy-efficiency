from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

SUPPORTED_CITIES: tuple[str, ...] = ("Milano", "Roma", "Napoli")
_SNAPSHOT_PATH = Path("data") / "forecast_prices.json"


def _normalize_city_key(value: str) -> str:
    return str(value).strip()


def _ensure_parent(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossibile creare la cartella per %s: %s", path, exc)


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_snapshot(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Carica il file JSON con le previsioni salvate, restituendo un dizionario per citta."""
    target = path or _SNAPSHOT_PATH
    if not target.exists():
        return {}
    try:
        raw = target.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossibile leggere %s: %s", target, exc)
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("File previsioni non valido (%s): %s", target, exc)
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    if not isinstance(payload, Mapping):
        return result

    for key, entry in payload.items():
        if not isinstance(entry, Mapping):
            continue
        per_hour_raw = entry.get("per_hour")
        if not isinstance(per_hour_raw, Sequence):
            continue
        per_hour: List[float] = []
        for item in per_hour_raw:
            coerced = _coerce_float(item)
            if coerced is not None:
                per_hour.append(coerced)
        if not per_hour:
            continue
        city_key = _normalize_city_key(str(entry.get("city") or key))
        result[city_key] = {
            "city": city_key,
            "start": entry.get("start"),
            "per_hour": per_hour,
            "meta": entry.get("meta") if isinstance(entry.get("meta"), Mapping) else {},
            "stored_at": entry.get("stored_at"),
        }
    return result


def _write_snapshot(content: Mapping[str, Any], path: Optional[Path] = None) -> None:
    target = path or _SNAPSHOT_PATH
    _ensure_parent(target)
    serializable = json.loads(json.dumps(content))
    try:
        target.write_text(json.dumps(serializable, indent=2, ensure_ascii=True), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Impossibile scrivere %s: %s", target, exc)


def record_payload(payload: Mapping[str, Any], path: Optional[Path] = None) -> bool:
    """Registra una previsione per una citta nel file snapshot."""
    city_raw = payload.get("city")
    per_hour_raw = payload.get("per_hour")

    city = _normalize_city_key(city_raw) if city_raw else ""
    if not city:
        logger.debug("Payload privo di citta: %s", payload)
        return False
    if not isinstance(per_hour_raw, Sequence):
        logger.debug("Payload privo di serie oraria: %s", payload)
        return False

    per_hour: List[float] = []
    for item in per_hour_raw:
        coerced = _coerce_float(item)
        if coerced is not None:
            per_hour.append(coerced)
    if not per_hour:
        logger.debug("Serie oraria vuota per %s nel payload %s", city, payload)
        return False

    existing = load_snapshot(path)
    entry = dict(existing.get(city, {}))
    entry.update(
        {
            "city": city,
            "start": payload.get("start"),
            "per_hour": per_hour,
            "meta": payload.get("meta") if isinstance(payload.get("meta"), Mapping) else {},
            "stored_at": _current_timestamp(),
        }
    )
    existing[city] = entry
    _write_snapshot(existing, path)
    return True


def _lookup_entry(city: str, snapshot: Optional[Mapping[str, Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    data = snapshot or load_snapshot()
    if not city:
        return None
    key = _normalize_city_key(city)
    if key in data:
        return dict(data[key])
    lowered = key.lower()
    for candidate_key, entry in data.items():
        if candidate_key.lower() == lowered:
            return dict(entry)
    return None


def get_city_payload(city: str, hours: Optional[int] = None) -> Optional[Dict[str, Any]]:
    entry = _lookup_entry(city)
    if not entry:
        return None
    per_hour: List[float] = list(entry.get("per_hour") or [])
    if not per_hour:
        return None
    if hours is not None and hours > 0:
        per_hour = _trim_or_pad(per_hour, hours)
    return {
        "city": entry.get("city") or _normalize_city_key(city),
        "start": entry.get("start"),
        "per_hour": per_hour,
        "meta": dict(entry.get("meta") or {}),
        "stored_at": entry.get("stored_at"),
    }


def get_city_per_hour(city: str, hours: Optional[int] = None) -> Optional[List[float]]:
    payload = get_city_payload(city, hours)
    if not payload:
        return None
    values = payload.get("per_hour") or []
    if not isinstance(values, list):
        return None
    return list(values)


def _trim_or_pad(series: Sequence[float], hours: int) -> List[float]:
    if hours <= 0:
        return []
    data = list(series)
    if len(data) >= hours:
        return data[:hours]
    if not data:
        return [0.25] * hours
    return data + [data[-1]] * (hours - len(data))


__all__ = [
    "SUPPORTED_CITIES",
    "get_city_payload",
    "get_city_per_hour",
    "load_snapshot",
    "record_payload",
]

