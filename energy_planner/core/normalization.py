"""Utility di normalizzazione per il modello di scheduling."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, MutableSequence, Optional, Sequence

logger = logging.getLogger(__name__)

SLOT_MINUTES = 5
MINUTES_PER_HOUR = 60
SLOTS_PER_HOUR = MINUTES_PER_HOUR // SLOT_MINUTES
DEFAULT_FLAT_PRICE = 0.25
DEFAULT_WORKFORCE_PER_SLOT = 1

_VAGUE_WINDOWS = {
    "dopo pranzo": ("13:00", "15:00"),
    "mattina": ("08:00", "12:00"),
    "pomeriggio": ("14:00", "18:00"),
    "sera": ("18:00", "21:00"),
    "notte": ("22:00", "06:00"),
}


@dataclass(slots=True)
class NormalizedWindow:
    """Intervallo temporale espresso in minuti da mezzanotte."""

    start_minute: int
    end_minute: int
    meta: Optional[dict[str, object]] = None


@dataclass(slots=True)
class NormalizedContext:
    """Risultato aggregato di normalizzazione per prezzi e workforce."""

    slot_minutes: int
    slots: int
    price_per_slot: List[float]
    workforce_per_slot: List[float]
    assumptions: List[str] = field(default_factory=list)


def parse_time(value: str) -> int:
    """Converte `HH:MM` in minuti da mezzanotte, sollevando ValueError se invalido."""
    try:
        hour_str, minute_str = value.strip().split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
    except (ValueError, AttributeError) as exc:  # pragma: no cover - protezione input
        raise ValueError(f"Formato orario non valido: {value}") from exc
    if not (0 <= hour < 24) or not (0 <= minute < 60):
        raise ValueError(f"Orario fuori range: {value}")
    return hour * MINUTES_PER_HOUR + minute


def snap_start(minute: int) -> int:
    """Arrotonda l inizio al multiplo di slot precedente."""
    return (minute // SLOT_MINUTES) * SLOT_MINUTES


def snap_end(minute: int) -> int:
    """Arrotonda la fine al primo multiplo di slot successivo."""
    if minute % SLOT_MINUTES == 0:
        return minute
    return ((minute // SLOT_MINUTES) + 1) * SLOT_MINUTES


def snap_duration(minutes: int) -> int:
    """Arrotonda la durata al multiplo di slot superiore."""
    if minutes <= 0:
        raise ValueError("La durata deve essere positiva")
    return snap_end(minutes)


def interpret_vague_expression(value: str) -> Optional[NormalizedWindow]:
    """Traduce espressioni vaghe in finestre standard con meta low-confidence."""
    key = value.strip().lower()
    if key not in _VAGUE_WINDOWS:
        return None
    start_str, end_str = _VAGUE_WINDOWS[key]
    start = snap_start(parse_time(start_str))
    end = snap_end(parse_time(end_str))
    if end <= start:
        end += 24 * MINUTES_PER_HOUR  # gestisci intervalli che attraversano la mezzanotte
    meta = {"confidence": "low", "source": "vague_expression", "original": value}
    return NormalizedWindow(start_minute=start, end_minute=end, meta=meta)


def minutes_to_slot(minute: int) -> int:
    """Restituisce l indice di slot corrispondente al minuto dato."""
    if minute < 0:
        raise ValueError("I minuti non possono essere negativi")
    return minute // SLOT_MINUTES


def build_price_series(
    *,
    horizon_hours: int,
    per_hour: Optional[Sequence[float]] = None,
    assumptions: Optional[MutableSequence[str]] = None,
    default_price: float = DEFAULT_FLAT_PRICE,
) -> List[float]:
    """Converte prezzi orari in una serie per slot, applicando fallback flat."""
    assumptions = assumptions if assumptions is not None else []
    total_slots = horizon_hours * SLOTS_PER_HOUR

    if not per_hour:
        assumptions.append("Prezzi mancanti: applicata serie flat 0.25 EUR/kWh.")
        logger.info("Prezzi assenti, applico flat %.2f", default_price)
        return [default_price] * total_slots

    hourly = list(per_hour)
    if horizon_hours > 0 and len(hourly) >= horizon_hours:
        series = []
        for value in hourly[:horizon_hours]:
            series.extend([float(value)] * SLOTS_PER_HOUR)
        return series
    if len(hourly) == 24:
        series: List[float] = []
        for value in hourly:
            series.extend([float(value)] * SLOTS_PER_HOUR)
        return series[:total_slots]

    assumptions.append(
        "Prezzi con cardinalita inattesa: applicata serie flat 0.25 EUR/kWh."
    )
    logger.warning("Lunghezza prezzi %s non compatibile, fallback flat.", len(hourly))
    return [default_price] * total_slots


def build_workforce_series(
    *,
    horizon_hours: int,
    shifts: Optional[Iterable[Mapping[str, object]]] = None,
    assumptions: Optional[MutableSequence[str]] = None,
    default_per_slot: float = DEFAULT_WORKFORCE_PER_SLOT,
) -> List[float]:
    """Trasforma i turni in disponibilita per slot, con fallback di sicurezza."""
    assumptions = assumptions if assumptions is not None else []
    total_slots = horizon_hours * SLOTS_PER_HOUR
    series = [0.0] * total_slots

    if not shifts:
        assumptions.append("Workforce non fornita: impostato default 1 persona per slot.")
        logger.info("Workforce assente, applico default_per_slot=%s", default_per_slot)
        return [default_per_slot] * total_slots

    for shift in shifts:
        try:
            start_str = str(shift["start"])
            end_str = str(shift["end"])
            people = float(shift.get("people", 0))
        except KeyError as exc:  # pragma: no cover - input difettoso
            logger.warning("Shift privo di chiavi necessarie: %s", shift)
            continue
        start = snap_start(parse_time(start_str))
        end = snap_end(parse_time(end_str))
        if end <= start:
            logger.warning("Shift con end <= start: %s", shift)
            continue
        start_slot = minutes_to_slot(start)
        end_slot = minutes_to_slot(end)
        for slot in range(start_slot, min(end_slot, total_slots)):
            series[slot] += people

    if all(value == 0 for value in series):
        assumptions.append("Workforce nulla risultante: impostato default 1 persona per slot.")
        logger.info("Workforce risultata nulla, applico default_per_slot=%s", default_per_slot)
        return [default_per_slot] * total_slots
    return series


def normalize_context(
    *,
    horizon_hours: int,
    per_hour_prices: Optional[Sequence[float]] = None,
    workforce_shifts: Optional[Iterable[Mapping[str, object]]] = None,
) -> NormalizedContext:
    """Crea un contesto normalizzato pronto per la validazione."""
    assumptions: List[str] = []
    price_series = build_price_series(
        horizon_hours=horizon_hours,
        per_hour=per_hour_prices,
        assumptions=assumptions,
    )
    workforce_series = build_workforce_series(
        horizon_hours=horizon_hours,
        shifts=workforce_shifts,
        assumptions=assumptions,
    )
    total_slots = horizon_hours * SLOTS_PER_HOUR
    return NormalizedContext(
        slot_minutes=SLOT_MINUTES,
        slots=total_slots,
        price_per_slot=price_series,
        workforce_per_slot=workforce_series,
        assumptions=assumptions,
    )


__all__ = [
    "SLOT_MINUTES",
    "NormalizedWindow",
    "NormalizedContext",
    "parse_time",
    "snap_start",
    "snap_end",
    "snap_duration",
    "interpret_vague_expression",
    "minutes_to_slot",
    "build_price_series",
    "build_workforce_series",
    "normalize_context",
]
