import logging
import math

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from conftest import assert_problem
from test_provider_validation import ET0, PAST, RAIN, valid_payload

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


def test_bug_is_500_without_details(monkeypatch, caplog, fake_provider, clock):
    async def broken_get(cell, days, past_days=0):
        raise ValueError("secret detail from a bug")

    use_fake_provider(monkeypatch, fake_provider)
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        monkeypatch.setattr(main.app.state.cache, "get", broken_get)
        response = test_client.get(FORECAST, params=POINT)
    body = assert_problem(response, 500, "UNAVAILABLE")
    assert body["detail"] == "Internal server error"
    assert "secret" not in response.text
    assert "secret detail from a bug" in caplog.text


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


def test_negative_zero_from_provider_served_as_zero(monkeypatch, clock):
    payload = valid_payload()
    # Index PAST + 1 is tomorrow, the second day served (before: index 1 of 8).
    payload["daily"][ET0][PAST + 1] = -0.0
    payload["daily"][RAIN][PAST + 1] = -0.0
    monkeypatch.setattr(main, "make_client", lambda settings: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))))
    with TestClient(main.app) as test_client:
        response = test_client.get(FORECAST, params=POINT)
    assert response.status_code == 200
    assert "-0.0" not in response.text
    day = response.json()["days"][1]
    assert day["et0_mm"] == 0.0 and day["rain_mm"] == 0.0
    assert math.copysign(1, day["et0_mm"]) == 1
    assert math.copysign(1, day["rain_mm"]) == 1


# --- past_days (W20-W23) ---


@pytest.mark.parametrize("value", ["-1", "93", "1.5", "", "nan", "abc"])
def test_bad_past_days_is_422(client, fake_provider, value):
    response = client.get(f"{FORECAST}?lat=31.25&lon=34.79&past_days={value}")
    body = assert_problem(response, 422, "VALIDATION")
    assert "past_days" in body["detail"]
    assert fake_provider.calls == 0


def test_past_days_zero_is_todays_response(client):
    without = client.get(FORECAST, params=POINT)
    zero = client.get(FORECAST, params={**POINT, "past_days": 0})
    assert without.status_code == zero.status_code == 200
    assert without.content == zero.content
    assert [d["date"] for d in zero.json()["days"]] == [f"2026-11-{15 + i}" for i in range(7)]


def test_past_days_three_adds_three_days_before_today(client):
    payload = valid_payload()
    response = client.get(FORECAST, params={**POINT, "past_days": 3})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"lat", "lon", "source", "fetched_at", "stale", "days"}
    assert len(body["days"]) == 10
    for i, day in enumerate(body["days"]):
        assert set(day) == {"date", "et0_mm", "rain_mm"}
        assert day["date"] == payload["daily"]["time"][PAST - 3 + i]
        assert day["et0_mm"] == payload["daily"][ET0][PAST - 3 + i]
        assert day["rain_mm"] == payload["daily"][RAIN][PAST - 3 + i]
    assert body["days"][3]["date"] == "2026-11-15"


def test_stale_answer_with_past_days(client, fake_provider, clock):
    assert client.get(FORECAST, params=POINT).status_code == 200
    clock.advance(4 * 3600)
    fake_provider.fail = True
    response = client.get(FORECAST, params={**POINT, "past_days": 92, "days": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["stale"] is True
    assert body["fetched_at"] == "2026-11-15T06:00:00Z"
    assert len(body["days"]) == 93
    assert body["days"][0]["date"] == "2026-08-15"
    assert body["days"][-1]["date"] == "2026-11-15"


def test_unusable_past_value_gives_503_only_with_past_days(monkeypatch, clock):
    payload = valid_payload()
    payload["daily"][ET0][0] = None
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(main, "make_client", lambda settings: httpx.AsyncClient(
        transport=httpx.MockTransport(handler)))
    with TestClient(main.app) as test_client:
        forecast_only = test_client.get(FORECAST, params=POINT)
        with_past = test_client.get(FORECAST, params={**POINT, "past_days": 1})
    assert forecast_only.status_code == 200
    assert forecast_only.json()["stale"] is False
    assert len(forecast_only.json()["days"]) == 7
    assert_problem(with_past, 503, "UNAVAILABLE")
    # W26: seconds until the entry's next refresh (fresh for 3 h, clock not moved).
    assert with_past.headers["retry-after"] == "10800"
    # Not a provider failure: one call, no retries, no pause.
    assert len(calls) == 1
