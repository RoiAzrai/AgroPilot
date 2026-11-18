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


@pytest.fixture
def client(monkeypatch, fake):
    """The whole app over the `fake` registry + weather (a fixture the test module provides).
    Settings come from env vars set here; no socket, no real .env."""
    import httpx
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setenv("REGISTRY_URL", "http://registry.invalid")
    monkeypatch.setenv("WEATHER_URL", "http://weather.invalid")
    monkeypatch.setattr(
        main, "make_client", lambda settings: httpx.AsyncClient(transport=fake.transport())
    )
    # raise_server_exceptions=False: a bug must reach the 500 handler, as in production.
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


def assert_problem(response, status: int, code: str) -> dict:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert set(body) == {"type", "title", "status", "detail", "code"}
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert body["code"] == code
    assert body["detail"]
    return body
