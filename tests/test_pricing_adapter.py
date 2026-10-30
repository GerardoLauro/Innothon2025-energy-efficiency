from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

import energy_planner.pricing.forecaster_adapter as adapter
from energy_planner.pricing.forecaster_adapter import (
    ForecasterClient,
    expand_per_hour_to_per_slot,
)


def test_expand_per_hour_to_per_slot_basic() -> None:
    per_hour = [0.1, 0.2]
    expanded = expand_per_hour_to_per_slot(per_hour)
    assert len(expanded) == 24
    assert expanded[:12] == [0.1] * 12
    assert expanded[12:] == [0.2] * 12


def test_predict_hourly_with_stub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    per_hour = [float(idx) for idx in range(24)]

    class DummyForecaster:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

        def load_and_prepare_data(self) -> dict[str, Any]:
            return {"ok": True}

    def fake_load_and_predict(*args: Any, **kwargs: Any) -> tuple[dict, Any, Any, Any]:
        return {}, None, [[value * 1000 for value in per_hour]], None

    module = types.SimpleNamespace(
        PriceForecaster=DummyForecaster,
        load_and_predict=fake_load_and_predict,
        datasets_path={
            "price": "price.csv",
            "consumption": "cons.csv",
            "weather": "weather.csv",
        },
        models_to_run=["NHITS"],
    )

    dummy_dir = tmp_path / "Price_forecaster" / "code"
    dummy_dir.mkdir(parents=True)
    dummy_file = dummy_dir / "Price_forecaster.py"
    dummy_file.write_text("# stub\n", encoding="utf-8")

    def fake_load_module_once(cls, module_path: Path) -> adapter._ModuleArtifacts:  # type: ignore[attr-defined]
        return adapter._ModuleArtifacts(module=module, module_path=module_path)

    monkeypatch.setattr(ForecasterClient, "_load_module_once", classmethod(fake_load_module_once))

    client = ForecasterClient(price_forecaster_root=str(dummy_dir), cache_ttl_minutes=0)
    result = client.predict_hourly("Milano", 24)
    assert len(result["per_hour"]) == 24
    assert result["per_hour"][5] == pytest.approx(per_hour[5])
    assert result["meta"]["source"] == "Price_forecaster"
