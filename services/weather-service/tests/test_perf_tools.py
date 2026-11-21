"""NFR-2.3 measurement tools (design 5.11). Localhost only: the fake provider
runs on an ephemeral port; Open-Meteo is never contacted."""

import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

from perf.fake_provider import make_server
from perf.run_session import session_exit_code, session_summary, zero_calls_check
from provider import FORECAST_DAYS, PAST_DAYS, parse_forecast


@pytest.fixture
def provider_url():
    server = make_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join()


def test_fake_provider_body_passes_strict_validation(provider_url):
    response = httpx.get(f"{provider_url}/v1/forecast", params={"latitude": 31.25, "longitude": 34.85})
    assert response.status_code == 200
    now = datetime.now(timezone.utc)
    forecast = parse_forecast(response.json(), now)
    assert forecast.timezone_name == "Asia/Jerusalem"
    today = now.astimezone(ZoneInfo("Asia/Jerusalem")).date()
    assert len(forecast.days) == PAST_DAYS + FORECAST_DAYS
    assert sum(d.date < today for d in forecast.days) == PAST_DAYS
    assert forecast.days[0].date == today - timedelta(days=PAST_DAYS)
    assert forecast.days[PAST_DAYS].date == today


def test_fake_provider_counts_calls(provider_url):
    assert httpx.get(f"{provider_url}/calls").json() == {"calls": 0}
    for lat in (31.25, 31.45):
        assert httpx.get(f"{provider_url}/v1/forecast", params={"latitude": lat}).status_code == 200
    # Reading the count is not a forecast call.
    assert httpx.get(f"{provider_url}/calls").json() == {"calls": 2}
    assert httpx.get(f"{provider_url}/calls").json() == {"calls": 2}
    assert httpx.get(f"{provider_url}/other").status_code == 404
    assert httpx.get(f"{provider_url}/calls").json() == {"calls": 2}


def report(exit_code: int, p95s: dict[str, float | None]) -> dict:
    endpoints = {name: {"latency_ms": {"p95": p95}} for name, p95 in p95s.items()}
    endpoints["OVERALL"] = {"latency_ms": {"p95": 1.0}}
    return {"endpoints": endpoints, "verdict": {"exit_code": exit_code}}


def test_session_summary():
    passing = [
        report(0, {"a": 10.0, "b": 12.5}),
        report(0, {"a": 40.0, "b": 8.0}),
        report(0, {"a": 9.0, "b": 11.0}),
    ]
    summary = session_summary(passing)
    assert summary["status"] == "PASS"
    assert summary["worst_p95_ms"] == 40.0
    assert summary["worst_run"] == 2
    assert summary["worst_endpoint"] == "a"
    assert summary["runs"] == ["PASS", "PASS", "PASS"]

    failing = [report(0, {"a": 10.0}), report(1, {"a": 150.0}), report(0, {"a": 9.0})]
    summary = session_summary(failing)
    assert summary["status"] == "FAIL"
    assert summary["worst_p95_ms"] == 150.0
    assert summary["runs"] == ["PASS", "FAIL", "PASS"]

    # An invalid run makes the whole session INVALID, even next to a FAIL.
    invalid = [report(1, {"a": 150.0}), report(0, {"a": 9.0}), report(2, {"a": None})]
    summary = session_summary(invalid)
    assert summary["status"] == "INVALID"
    assert summary["worst_p95_ms"] == 150.0
    assert summary["runs"] == ["FAIL", "PASS", "INVALID"]

    # No successful request anywhere: no worst p95.
    summary = session_summary([report(1, {"a": None})] * 3)
    assert summary["status"] == "FAIL"
    assert summary["worst_p95_ms"] is None


def test_zero_calls_check():
    assert zero_calls_check(3, 3) == {"passed": True, "calls_during_runs": 0}
    assert zero_calls_check(3, 4) == {"passed": False, "calls_during_runs": 1}


def test_session_exit_code():
    ok = {"passed": True, "calls_during_runs": 0}
    calls = {"passed": False, "calls_during_runs": 2}
    assert session_exit_code({"status": "PASS"}, ok) == 0
    assert session_exit_code({"status": "FAIL"}, ok) == 1
    assert session_exit_code({"status": "INVALID"}, ok) == 2
    # Provider calls during the runs fail the session whatever the timings say.
    assert session_exit_code({"status": "PASS"}, calls) == 1
    assert session_exit_code({"status": "INVALID"}, calls) == 1


def test_runner_warms_the_points_the_load_tool_requests():
    from perf import load_test, run_session

    assert run_session.POINTS == load_test.POINTS
