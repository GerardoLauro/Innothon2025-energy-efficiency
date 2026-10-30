"""Keep each test independent of local sessions, credentials and networks."""
from pathlib import Path
import socket

import pytest


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("LLM_PROVIDER", "API_KEY", "API_BASE_URL", "API_MODEL", "PROMPTS_DIR",
                 "PRICE_FORECASTER_ROOT", "PRICE_CACHE_DIR", "CBC_PATH", "EURIS_DATA_PATH"):
        monkeypatch.delenv(name, raising=False)

    def no_network(*args, **kwargs):
        raise AssertionError("Network access is forbidden in the offline test suite")

    monkeypatch.setattr(socket.socket, "connect", no_network)


@pytest.fixture
def repository_root():
    return Path(__file__).resolve().parents[1]
