import logging

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from conftest import assert_problem

FORECAST = "/v1/forecast"
POINT = {"lat": 31.25, "lon": 34.79}


def use_fake_provider(monkeypatch, fake_provider):
    monkeypatch.setattr(main, "make_client", lambda settings: httpx.AsyncClient(
        transport=httpx.MockTransport(fake_provider.handler)))


def test_spec_example_shape(client):
    response = client.get(FORECAST, params=POINT)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"lat", "lon", "source", "fetched_at", "stale", "days"}
    assert body["lat"] == 31.25
    assert body["lon"] == 34.79
    assert body["source"] == "open-meteo"
    assert body["fetched_at"] == "2026-11-15T06:00:00Z"
    assert body["stale"] is False
    for day in body["days"]:
        assert set(day) == {"date", "et0_mm", "rain_mm"}
    assert body["days"][0] == {"date": "2026-11-15", "et0_mm": 1.5, "rain_mm": 0.0}


def test_provider_asked_for_cell_center(client, fake_provider):
    client.get(FORECAST, params=POINT)
    assert fake_provider.points == [(31.25, 34.75)]


def test_default_days_is_seven(client):
    body = client.get(FORECAST, params=POINT).json()
    assert [d["date"] for d in body["days"]] == [f"2026-11-{15 + i}" for i in range(7)]


@pytest.mark.parametrize(
    "query",
    [
        "lat=-90.1&lon=34.79",
        "lat=90.1&lon=34.79",
        "lat=31.25&lon=-180.1",
        "lat=31.25&lon=180.1",
        "lat=31.25&lon=34.79&days=0",
        "lat=31.25&lon=34.79&days=8",
        "lat=31.25&lon=34.79&days=7.5",
        "lat=31.25abc&lon=34.79",
        "lat=&lon=34.79",
        "lat=nan&lon=34.79",
        "lat=31.25&lon=inf",
        "lon=34.79",
        "lat=31.25",
    ],
)
def test_validation_422(client, fake_provider, query):
    assert_problem(client.get(f"{FORECAST}?{query}"), 422, "VALIDATION")
    assert fake_provider.calls == 0


@pytest.mark.parametrize(
    "query",
    [
        "lat=-90&lon=34.79",
        "lat=90&lon=34.79",
        "lat=31.25&lon=-180",
        "lat=31.25&lon=180",
        "lat=31.25&lon=34.79&days=1",
        "lat=31.25&lon=34.79&days=7",
    ],
)
def test_boundaries_200(client, query):
    response = client.get(f"{FORECAST}?{query}")
    assert response.status_code == 200


def test_days_count(client):
    assert len(client.get(FORECAST, params={**POINT, "days": 3}).json()["days"]) == 3


def test_no_provider_names_in_body(client):
    text = client.get(FORECAST, params=POINT).text
    for name in ("et0_fao", "precipitation", "daily"):
        assert name not in text


def test_provider_down_no_cache_is_503(client, fake_provider):
    fake_provider.fail = True
    response = client.get(FORECAST, params=POINT)
    body = assert_problem(response, 503, "UNAVAILABLE")
    assert body["detail"] == "Forecast unavailable"
    assert response.headers["retry-after"] == "60"
    assert "provider" not in response.text.lower()
    assert "500" not in response.text


def test_provider_down_with_cache_is_stale_200(client, fake_provider, clock):
    assert client.get(FORECAST, params=POINT).json()["stale"] is False
    clock.advance(4 * 3600)
    fake_provider.fail = True
    response = client.get(FORECAST, params=POINT)
    assert response.status_code == 200
    body = response.json()
    assert body["stale"] is True
    assert body["fetched_at"] == "2026-11-15T06:00:00Z"
    assert fake_provider.calls == 1 + 3


def test_health_with_provider_down(client, fake_provider):
    fake_provider.fail = True
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert fake_provider.calls == 0


def test_unknown_route_404(client):
    body = assert_problem(client.get("/nope"), 404, "NOT_FOUND")
    assert body["detail"] == "No route matches /nope"


def test_wrong_method_405(client):
    assert_problem(client.post(FORECAST, params=POINT), 405, "VALIDATION")


def test_bug_is_500_without_details(monkeypatch, fake_provider, clock):
    async def broken_get(cell, days):
        raise ValueError("secret detail from a bug")

    use_fake_provider(monkeypatch, fake_provider)
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        monkeypatch.setattr(main.app.state.cache, "get", broken_get)
        response = test_client.get(FORECAST, params=POINT)
    body = assert_problem(response, 500, "UNAVAILABLE")
    assert body["detail"] == "Internal server error"
    assert "secret" not in response.text


def test_startup_fails_without_base_url(monkeypatch):
    monkeypatch.delenv("PROVIDER_BASE_URL")
    with pytest.raises(RuntimeError, match="PROVIDER_BASE_URL"):
        with TestClient(main.app):
            pass


def test_key_not_in_logs_or_body(monkeypatch, caplog, fake_provider, clock):
    monkeypatch.setenv("PROVIDER_API_KEY", "secret-key-123")
    use_fake_provider(monkeypatch, fake_provider)
    caplog.set_level(logging.DEBUG)
    with TestClient(main.app) as test_client:
        ok = test_client.get(FORECAST, params=POINT)
        clock.advance(4 * 3600)
        fake_provider.fail = True
        stale = test_client.get(FORECAST, params=POINT)
        down = test_client.get(FORECAST, params={"lat": 10.05, "lon": 10.05})
    assert [ok.status_code, stale.status_code, down.status_code] == [200, 200, 503]
    for response in (ok, stale, down):
        assert "secret-key-123" not in response.text
    assert "secret-key-123" not in caplog.text
    for record in caplog.records:
        assert "secret-key-123" not in record.getMessage()
