from __future__ import annotations

import logging
from typing import Iterable

from energy_planner.pricing import forecast_store
from energy_planner.pricing.forecaster_adapter import ForecasterClient

logger = logging.getLogger(__name__)


def _normalize_cities(cities: Iterable[str] | None) -> list[str]:
    if cities is None:
        return list(forecast_store.SUPPORTED_CITIES)
    normalized: list[str] = []
    for city in cities:
        value = str(city).strip()
        if value:
            normalized.append(value)
    return normalized


def bootstrap_snapshot(
    cities: Iterable[str] | None = None,
    *,
    hours: int = 24,
    force: bool = False,
) -> bool:
    """Genera (o aggiorna) il file JSON con le previsioni per citta."""
    city_list = _normalize_cities(cities)
    if not city_list:
        logger.debug("Nessuna citta specificata per la generazione delle previsioni.")
        return False

    pending: list[str] = []
    if force:
        pending = city_list
    else:
        for city in city_list:
            payload = forecast_store.get_city_payload(city, hours)
            per_hour = payload.get("per_hour") if payload else None
            if not per_hour or len(per_hour) < hours:
                pending.append(city)

    if not pending:
        logger.debug("Previsioni gia presenti per tutte le citta richieste.")
        return False

    client = ForecasterClient()
    generated = False
    for city in pending:
        try:
            payload = client.predict_hourly(city, hours)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Impossibile generare la previsione iniziale per %s: %s", city, exc)
            continue
        try:
            forecast_store.record_payload(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Registrazione della previsione per %s non riuscita: %s", city, exc)
        generated = True
    return generated


__all__ = ["bootstrap_snapshot"]
