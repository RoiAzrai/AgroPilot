import warnings
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

with warnings.catch_warnings():
    # Judgment log 11: keep httpx for the TestClient. Its import-time
    # deprecation warning is ignored here only, so `-W error` stays usable.
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

import config
import main
from fakes import FakeClock
from test_provider_validation import valid_payload

PROVIDER_HOST = "provider.invalid"
START = datetime(2026, 11, 15, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer's .env must never leak into tests.
    monkeypatch.setenv("PROVIDER_BASE_URL", "http://provider.invalid/v1/forecast")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "no-such.env")


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


class FakeProvider:
    """MockTransport handler: a valid 100-day answer (92 past + 8 forecast days)
    for any point, or a 500
    while `fail` is set. Any host but provider.invalid fails the test."""

    def __init__(self) -> None:
        self.calls = 0
        self.points: list[tuple[float, float]] = []
        self.fail = False
        self.foreign_hosts: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host != PROVIDER_HOST:
            self.foreign_hosts.append(request.url.host)
            raise AssertionError(f"request to a host other than {PROVIDER_HOST}")
        self.calls += 1
        params = request.url.params
        self.points.append((float(params["latitude"]), float(params["longitude"])))
        if self.fail:
            return httpx.Response(500)
        return httpx.Response(200, json=valid_payload())


@pytest.fixture
def fake_provider():
    provider = FakeProvider()
    yield provider
    assert not provider.foreign_hosts, f"requests to other hosts: {provider.foreign_hosts}"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock(START)
    monkeypatch.setattr(main, "utc_now", fake.now)
    return fake


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, fake_provider: FakeProvider, clock: FakeClock):
    def make_client(settings: config.Settings) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(fake_provider.handler))

    monkeypatch.setattr(main, "make_client", make_client)
    with TestClient(main.app) as test_client:
        yield test_client
