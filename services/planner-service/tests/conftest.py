import pytest

import config

SERVICE_KEYS = [
    "REGISTRY_URL",
    "WEATHER_URL",
    "REGISTRY_TIMEOUT_SECONDS",
    "WEATHER_TIMEOUT_SECONDS",
    "MAX_DAILY_RUN_MINUTES",
    "DEPLETION_FRACTION_OVERRIDE",
    "WEATHER_REFRESH_DEADLINE_SECONDS",
    "RETRY_AFTER_SECONDS",
]


@pytest.fixture(autouse=True)
def ignore_real_env(tmp_path, monkeypatch):
    # A developer's .env and shell env must never leak into any test.
    for key in SERVICE_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "no-such.env")
