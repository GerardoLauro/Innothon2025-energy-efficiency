from __future__ import annotations

import difflib
import importlib.util
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

from energy_planner.pricing import forecast_store


_CANONICAL_CITIES = {"milano": "Milano", "roma": "Roma", "napoli": "Napoli"}
_CITY_ALIASES = {
    "milan": "Milano",
    "rome": "Roma",
    "naples": "Napoli",
    "naple": "Napoli",
    "napoli": "Napoli",
    "roma": "Roma",
    "milano": "Milano",
    "rom": "Roma",
    "neapol": "Napoli",
}
_FALLBACK_PRICE = 0.25
_ROME_TZ_NAME = "Europe/Rome"
_SLOTS_PER_HOUR = 12

logger = logging.getLogger(__name__)


def _get_rome_now() -> datetime:
    """Return current datetime localized in Europe/Rome if available, otherwise naive UTC."""
    if ZoneInfo is None:
        return datetime.utcnow()
    try:
        return datetime.now(ZoneInfo(_ROME_TZ_NAME))
    except Exception:  # noqa: BLE001
        return datetime.utcnow()


def _ensure_timezone_awareness(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt
    if ZoneInfo is None:
        return dt
    try:
        return dt.replace(tzinfo=ZoneInfo(_ROME_TZ_NAME))
    except Exception:  # noqa: BLE001
        return dt


def _make_iso_without_tz(dt: datetime) -> str:
    aware = _ensure_timezone_awareness(dt)
    if ZoneInfo is not None:
        try:
            aware = aware.astimezone(ZoneInfo(_ROME_TZ_NAME))
        except Exception:  # noqa: BLE001
            pass
    naive = aware.replace(tzinfo=None)
    return naive.strftime("%Y-%m-%dT%H:%M:%S")


def expand_per_hour_to_per_slot(per_hour: Iterable[float]) -> List[float]:
    """Expand hourly prices into 5-minute slots (12 slots per hour).

    >>> len(expand_per_hour_to_per_slot([0.1, 0.2]))
    24
    """
    expanded: List[float] = []
    for value in per_hour:
        expanded.extend([float(value)] * _SLOTS_PER_HOUR)
    return expanded


@dataclass(frozen=True)
class _ModuleArtifacts:
    module: Any
    module_path: Path


class ForecasterClient:
    """Adapter that wraps the legacy Price_forecaster module."""

    _module_cache: Dict[Path, _ModuleArtifacts] = {}
    _module_lock = Lock()

    @staticmethod
    def _resolve_path(value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return path.expanduser().resolve()

    @staticmethod
    def _parse_int(value: Optional[str], default: Optional[int]) -> Optional[int]:
        if value is None:
            return default
        text = str(value).strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            logger.warning("Valore PRICE_CACHE_TTL_MIN non valido (%s), uso default=%s", value, default)
            return default

    def __init__(
        self,
        price_forecaster_root: str | Path | None = None,
        cache_dir: str | Path | None = None,
        cache_ttl_minutes: Optional[int] = None,
    ) -> None:
        root_env = os.environ.get("PRICE_FORECASTER_ROOT")
        default_root = str(Path.cwd() / "price_forecaster/code")
        if not Path(default_root).is_dir():
            default_root = str(Path(__file__).resolve().parents[2] / "price_forecaster/code")
        root_value = price_forecaster_root if price_forecaster_root is not None else root_env or default_root
        resolved_root = self._resolve_path(root_value)
        if not resolved_root.exists():
            legacy_root = self._resolve_path("./price_forecaster/code")
            resolved_root = legacy_root if legacy_root.exists() else resolved_root
        self._root = resolved_root

        ttl_env = os.environ.get("PRICE_CACHE_TTL_MIN")
        ttl_value = cache_ttl_minutes if cache_ttl_minutes is not None else self._parse_int(ttl_env, default=120)
        if ttl_value is None or ttl_value <= 0:
            self._cache_expiry: Optional[timedelta] = None
        else:
            self._cache_expiry = timedelta(minutes=ttl_value)

        cache_env = os.environ.get("PRICE_CACHE_DIR")
        cache_value = cache_dir if cache_dir is not None else cache_env or str(Path.cwd() / "data/price_cache")
        if not cache_value or self._cache_expiry is None:
            self._cache_dir_path: Optional[Path] = None
        else:
            self._cache_dir_path = self._resolve_path(cache_value)

        if self._cache_dir_path is None or self._cache_expiry is None:
            logger.info("Price cache disabilitata (ttl=%s, dir=%s)", ttl_value, cache_value)
        else:
            logger.info(
                "Price cache attiva in %s (ttl=%s min)",
                self._cache_dir_path,
                ttl_value,
            )

        self._module_path: Optional[Path] = None
        self._artifacts: Optional[_ModuleArtifacts] = None

        self._forecaster = None
        self._dataset = None
        self._load_and_predict = None
        self._models_to_run: List[str] = []
        self._datasets_path: Dict[str, str] = {}
        self._warmup_done = False
        self._warmup_error: Optional[Exception] = None
        self._PriceForecaster = None

        try:
            self._module_path = self._resolve_module_path(self._root)
        except FileNotFoundError as exc:
            self._warmup_error = exc

    # region public API -----------------------------------------------------------------
    def warmup(self) -> None:
        if self._warmup_done:
            return

        try:
            if self._artifacts is None and self._module_path is not None and self._warmup_error is None:
                self._artifacts = self._load_module_once(self._module_path)
            if self._artifacts is None:
                if self._warmup_error is None:
                    self._warmup_error = RuntimeError("Price_forecaster module unavailable")
                return

            self._hydrate_symbols()
            self._instantiate_forecaster()
        except Exception as exc:  # noqa: BLE001
            self._warmup_error = exc
        finally:
            self._warmup_done = True

    def predict_hourly(self, city: str, hours: int = 24) -> Dict[str, Any]:
        if hours <= 0:
            raise ValueError("hours must be a positive integer")

        normalized_city, meta_overrides = self._normalize_city(city)
        reason: Optional[str] = None

        try:
            self.warmup()
            if self._warmup_error:
                raise RuntimeError(f"warmup failed: {self._warmup_error}") from self._warmup_error
            if self._forecaster is None or self._dataset is None or self._load_and_predict is None:
                raise RuntimeError("forecaster module not ready")

            start_dt = _get_rome_now().replace(minute=0, second=0, microsecond=0)

            cached = self._read_cache(normalized_city, start_dt, hours)
            if cached is not None:
                cached["meta"].update(meta_overrides)
                return cached

            model_key = self._select_model_key(self._models_to_run)

            metrics, _, y_pred_denorm, _ = self._load_and_predict(
                self._forecaster,
                self._dataset,
                model_key=model_key,
                save_dir=str(self._module_path.parent.parent / "models"),
                show_plots=False,
                show_intervals=False,
                horizon=hours,
            )
        except Exception as exc:  # noqa: BLE001
            reason = str(exc)[:120]
            logger.warning("Falling back to flat prices for %s: %s", normalized_city, reason)
            return self._fallback_payload(normalized_city, hours, meta_overrides=meta_overrides, reason=reason)

        latest_forecast = self._extract_latest_sequence(y_pred_denorm, hours)
        per_hour = [float(value) / 1000.0 for value in latest_forecast]

        payload = {
            "city": normalized_city,
            "start": _make_iso_without_tz(start_dt),
            "per_hour": per_hour,
            "meta": {
                "source": "Price_forecaster",
                "simulazione": meta_overrides.get("simulazione", False),
                **{k: v for k, v in meta_overrides.items() if k != "simulazione"},
            },
        }

        try:
            forecast_store.record_payload(payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Impossibile salvare la previsione nel file JSON: %s", exc)

        if start_dt.date() == _get_rome_now().date():
            self._write_cache(normalized_city, start_dt, payload, hours)

        return payload

    # endregion -------------------------------------------------------------------------

    # region helpers --------------------------------------------------------------------
    @staticmethod
    def _resolve_module_path(root: Path) -> Path:
        root = root.expanduser()
        if root.is_file():
            return root.resolve()
        candidate = root / "Price_forecaster.py"
        if candidate.exists():
            return candidate.resolve()
        raise FileNotFoundError(f"Cannot locate Price_forecaster.py in {root}")

    @classmethod
    def _load_module_once(cls, module_path: Path) -> _ModuleArtifacts:
        with cls._module_lock:
            cached = cls._module_cache.get(module_path)
            if cached is not None:
                return cached

            module_name = f"_price_forecaster_{abs(hash(module_path))}"
            spec = importlib.util.spec_from_file_location(module_name, str(module_path))
            if spec is None or spec.loader is None:
                raise ImportError(f"Unable to create import spec for {module_path}")

            module = importlib.util.module_from_spec(spec)
            loader = spec.loader
            sys.modules[module_name] = module
            try:
                loader.exec_module(module)  # type: ignore[attr-defined]
            except Exception:
                sys.modules.pop(module_name, None)
                raise

            artifacts = _ModuleArtifacts(module=module, module_path=module_path)
            cls._module_cache[module_path] = artifacts
            return artifacts

    def _hydrate_symbols(self) -> None:
        if self._artifacts is None:
            raise RuntimeError("Price_forecaster artifacts not available")
        module = self._artifacts.module

        for flag_name in (
            "show_plots",
            "SHOW_PLOTS",
            "generate_plots",
            "GENERATE_PLOTS",
            "enable_plots",
            "ENABLE_PLOTS",
            "plots_enabled",
            "PLOTS_ENABLED",
        ):
            if hasattr(module, flag_name):
                try:
                    setattr(module, flag_name, False)
                except Exception:  # noqa: BLE001
                    logger.debug("Impossibile disattivare flag di plotting %s", flag_name)

        self._PriceForecaster = getattr(module, "PriceForecaster", None)
        self._load_and_predict = getattr(module, "load_and_predict", None)
        if not callable(self._load_and_predict) or self._PriceForecaster is None:
            raise AttributeError("PriceForecaster or load_and_predict not available in Price_forecaster module")

        raw_datasets_path = getattr(module, "datasets_path", None)
        self._datasets_path = self._make_datasets_path(raw_datasets_path)

        raw_models_to_run = getattr(module, "models_to_run", None)
        self._models_to_run = self._normalize_models_to_run(raw_models_to_run)

    def _instantiate_forecaster(self) -> None:
        try:
            self._forecaster = self._PriceForecaster(datasets_path=self._datasets_path)  # type: ignore[misc]
            self._dataset = self._forecaster.load_and_prepare_data()
        except Exception as exc:  # noqa: BLE001
            self._forecaster = None
            self._dataset = None
            raise RuntimeError("Unable to initialize PriceForecaster") from exc

    def _make_datasets_path(self, raw: Optional[Dict[str, Any]]) -> Dict[str, str]:
        if not isinstance(raw, dict):
            raw = {
                "price": "datasets_folder/Prices_dataset.csv",
                "consumption": "datasets_folder/Consumi_Orari_2024.csv",
                "weather": "datasets_folder/Weather_2024_2025.csv",
            }

        resolved: Dict[str, str] = {}
        base_path = self._module_path.parent if self._module_path else self._root
        for key, value in raw.items():
            path = Path(str(value))
            if not path.is_absolute():
                path = (base_path / path).resolve()
            resolved[key] = str(path)
        return resolved

    @staticmethod
    def _normalize_models_to_run(raw: Any) -> List[str]:
        if raw is None:
            return ["NHITS"]
        if isinstance(raw, str):
            return [raw.strip() or "NHITS"]
        if isinstance(raw, (list, tuple, set)):
            cleaned = [str(item).strip() for item in raw if str(item).strip()]
            return cleaned or ["NHITS"]
        return ["NHITS"]

    @staticmethod
    def _select_model_key(models: List[str]) -> str:
        if not models:
            return "NHITS"
        model = models[0] or "NHITS"
        return model.upper()

    @staticmethod
    def _extract_latest_sequence(y_pred_denorm: Any, hours: int) -> List[float]:
        try:
            import numpy as np  # type: ignore

            arr = np.asarray(y_pred_denorm, dtype=float)
        except Exception:  # noqa: BLE001
            try:
                arr = list(y_pred_denorm)
            except Exception as exc:  # noqa: BLE001
                raise ValueError("Unable to interpret prediction output") from exc

        if hasattr(arr, "ndim") and getattr(arr, "ndim", 1) > 1:
            latest = arr[-1]
        else:
            latest = arr

        sequence = list(map(float, list(latest)))
        if len(sequence) >= hours:
            return sequence[:hours]

        if not sequence:
            sequence = [float(_FALLBACK_PRICE * 1000)]

        sequence.extend([sequence[-1]] * (hours - len(sequence)))
        return sequence

    @staticmethod
    def _normalize_city(city: str) -> Tuple[str, Dict[str, Any]]:
        if not city:
            return "Milano", {"simulazione": True, "note": "empty city input routed to Milano"}

        city_key = city.strip().lower()
        if city_key in _CITY_ALIASES:
            target = _CITY_ALIASES[city_key]
            return target, {"simulazione": False}

        if city_key in _CANONICAL_CITIES:
            target = _CANONICAL_CITIES[city_key]
            return target, {"simulazione": False}

        matches = difflib.get_close_matches(city_key, list(_CANONICAL_CITIES.keys()), n=1)
        target = _CANONICAL_CITIES.get(matches[0], "Milano") if matches else "Milano"
        note = f"{city} non supportata: simulazione basata su {target}"
        return target, {"simulazione": True, "note": note}

    def _fallback_payload(
        self,
        city: str,
        hours: int,
        *,
        meta_overrides: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        start_dt = _get_rome_now().replace(minute=0, second=0, microsecond=0)
        snapshot_payload = forecast_store.get_city_payload(city, hours)
        if snapshot_payload:
            per_hour_snapshot = snapshot_payload.get("per_hour") or []
            if per_hour_snapshot:
                per_hour_values = [float(value) for value in per_hour_snapshot]
                meta_snapshot = dict(snapshot_payload.get("meta") or {})
                meta_snapshot.setdefault("source", meta_snapshot.get("source", "forecast_snapshot"))
                if reason and "reason" not in meta_snapshot:
                    meta_snapshot["reason"] = reason
                if meta_overrides:
                    for key, value in meta_overrides.items():
                        if key == "simulazione":
                            continue
                        meta_snapshot[key] = value
                meta_snapshot["simulazione"] = True
                meta_snapshot["archived_snapshot"] = True
                stored_city = snapshot_payload.get("city") or city
                start_value = snapshot_payload.get("start") or _make_iso_without_tz(start_dt)
                return {
                    "city": stored_city,
                    "start": start_value,
                    "per_hour": per_hour_values,
                    "meta": meta_snapshot,
                }

        per_hour = [float(_FALLBACK_PRICE)] * hours
        meta: Dict[str, Any] = {
            "source": "flat_fallback",
            "simulazione": True,
        }
        if reason:
            meta["reason"] = reason
        if meta_overrides:
            for key, value in meta_overrides.items():
                if key == "simulazione":
                    continue
                meta[key] = value
        return {
            "city": city,
            "start": _make_iso_without_tz(start_dt),
            "per_hour": per_hour,
            "meta": meta,
        }

    def _cache_dir(self) -> Optional[Path]:
        return self._cache_dir_path

    def _cache_path(self, city: str, dt: datetime, hours: int) -> Path:
        cache_dir = self._cache_dir()
        if cache_dir is None:
            raise RuntimeError("Cache directory unavailable")
        filename = f"{city}_{dt.strftime('%Y%m%d%H')}_{hours}.json"
        return cache_dir / filename

    def _read_cache(self, city: str, dt: datetime, hours: int) -> Optional[Dict[str, Any]]:
        if self._cache_expiry is None or self._cache_dir_path is None:
            return None

        if dt.date() != _get_rome_now().date():
            return None

        cache_file = self._cache_path(city, dt, hours)
        if not cache_file.exists():
            return None

        try:
            with cache_file.open("r", encoding="utf-8") as fp:
                payload = json.load(fp)
        except Exception:  # noqa: BLE001
            return None

        cached_at_raw = payload.get("meta", {}).get("cached_at") or payload.get("cached_at")
        if cached_at_raw:
            try:
                cached_at = datetime.fromisoformat(cached_at_raw)
            except ValueError:
                cached_at = None
        else:
            cached_at = None

        now_dt = _get_rome_now()
        if now_dt.tzinfo is not None:
            now_dt = now_dt.replace(tzinfo=None)

        if cached_at is None or now_dt - cached_at > self._cache_expiry:
            return None

        payload["meta"]["source"] = payload["meta"].get("source", "Price_forecaster")
        payload["meta"]["simulazione"] = payload["meta"].get("simulazione", False)
        return payload

    def _write_cache(self, city: str, dt: datetime, payload: Dict[str, Any], hours: int) -> None:
        if self._cache_expiry is None or self._cache_dir_path is None:
            return

        cache_dir = self._cache_dir()
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            return

        enriched = json.loads(json.dumps(payload))
        enriched.setdefault("meta", {})
        enriched["meta"]["cached_at"] = _make_iso_without_tz(_get_rome_now())
        cache_file = self._cache_path(city, dt, hours)

        try:
            with cache_file.open("w", encoding="utf-8") as fp:
                json.dump(enriched, fp, ensure_ascii=True, indent=2)
        except Exception:  # noqa: BLE001
            return

    # endregion -------------------------------------------------------------------------


def _quick_checks() -> None:
    client = ForecasterClient()
    result = client.predict_hourly("Milano", 24)
    assert len(result["per_hour"]) == 24, "Expected 24 hourly values"
    assert result["meta"].get("source"), "source should not be empty"
    assert len(expand_per_hour_to_per_slot([0.1, 0.2])) == 24, "5-minute slot expansion mismatch"


if __name__ == "__main__":  # pragma: no cover
    _quick_checks()
