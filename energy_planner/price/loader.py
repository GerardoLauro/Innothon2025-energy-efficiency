"""Caricamento e normalizzazione delle serie di prezzo."""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, List

from energy_planner.core.normalization import SLOTS_PER_HOUR

logger = logging.getLogger(__name__)

_DATA_DIR = Path("data/prices")


class PriceUnavailableError(FileNotFoundError):
    """Errore sollevato quando non sono disponibili prezzi per la citta richiesta."""

    def __init__(self, city: str) -> None:
        message = (
            f"Prezzi non disponibili per '{city}'. Incolla i 24 valori orari "
            "oppure imposta una serie flat di test."
        )
        super().__init__(message)


def load_city_hourly(city: str, when: date | None = None) -> List[float]:
    """Carica i prezzi orari per una citta dalle risorse locali."""
    path = _DATA_DIR / f"{city.lower()}.json"
    if not path.exists():
        logger.error("File prezzi assente: %s", path)
        raise PriceUnavailableError(city)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list) or len(payload) != 24:
        logger.error("Formato prezzi non valido in %s: attesi 24 valori", path)
        raise ValueError(f"Il file {path} deve contenere 24 valori orari.")
    logger.debug("Caricati prezzi orari per %s (primi 3 valori: %s)", city, payload[:3])
    return [float(value) for value in payload]


def upsample_hourly_to_slots(hourly: Iterable[float]) -> List[float]:
    """Replica ogni valore orario su 12 slot da 5 minuti."""
    series: List[float] = []
    for value in hourly:
        series.extend([float(value)] * SLOTS_PER_HOUR)
    logger.debug("Upsample completato: %s slot generati", len(series))
    return series

_HOURLY_LINE = re.compile(
    r"^\s*(?P<hour>[01]?\d|2[0-3])(?::[0-5]\d)?"
    r"(?:\s*[:;=\-]\s*|\s+)(?P<value>[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+))\s*$"
)


def parse_user_hourly_series(text: str) -> List[float]:
    """Parsa stringhe incollate dall'utente in 24 valori float."""
    def validate_values(items) -> List[float]:
        if len(items) != 24:
            raise ValueError("Sono necessari esattamente 24 valori orari.")
        values = [float(str(value).replace(",", ".")) for value in items]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("I prezzi devono essere numeri finiti.")
        return values

    text = text.strip()
    if text.startswith("["):
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError("I prezzi devono essere una lista JSON.")
        return validate_values(payload)

    lines = [line for line in text.splitlines() if line.strip()]
    matches = [_HOURLY_LINE.fullmatch(line) for line in lines]
    if len(matches) == 24 and all(matches):
        by_hour = {int(m.group("hour")): m.group("value") for m in matches}
        if set(by_hour) != set(range(24)):
            raise ValueError("Indicare ogni ora da 0 a 23 una sola volta.")
        return validate_values([by_hour[hour] for hour in range(24)])

    # A dot denotes decimal values in a comma-separated list. Decimal commas
    # are supported with whitespace or semicolon separators, avoiding ambiguity.
    patterns = [r"[,;\s]+", r"[;\s]+"] if "." in text else [r"[;\s]+", r"[,;\s]+"]
    for pattern in patterns:
        items = [item for item in re.split(pattern, text) if item]
        if len(items) == 24:
            try:
                return validate_values(items)
            except ValueError:
                continue
    raise ValueError("Impossibile interpretare i 24 prezzi: usare JSON, virgole con decimali a punto, o punto e virgola con decimali a virgola.")


__all__ = [
    "PriceUnavailableError",
    "load_city_hourly",
    "upsample_hourly_to_slots",
    "parse_user_hourly_series",
]
