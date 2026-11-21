from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest

import main
from conftest import assert_problem
from fakes import FAKE_TODAY, PLOT_ID, FakeUpstreams

REGISTRY, WEATHER = "registry-service", "weather-service"
BODY_KEYS = {
    "plot_id", "last_irrigation", "suggestion", "exact", "reason",
    "past_days_requested", "past_days_returned", "stale",
}


@pytest.fixture
def fake():
    return FakeUpstreams()


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    # Noon UTC on FAKE_TODAY: the latest date on Earth (UTC+14) is the day after.
    monkeypatch.setattr(main, "utc_now", lambda: datetime(2031, 6, 1, 12, tzinfo=UTC))


def planted(season_day: int) -> str:
    """Planting date that makes FAKE_TODAY season day `season_day`."""
    return (FAKE_TODAY - timedelta(days=season_day - 1)).isoformat()


def flat(fake: FakeUpstreams, et0: float = 5.0, rain: float = 0.0) -> None:
    def edit(body):
        for d in body["days"]:
            d["et0_mm"], d["rain_mm"] = et0, rain

    fake.edit("forecast", edit)


def case4(fake: FakeUpstreams) -> None:
    """Cases.md case 4: tomato, sand (83), today = season day 80, ET0 5.0, no rain."""
    fake.bodies["plot"]["planting_date"] = planted(80)
    flat(fake)


def days_back(n: int) -> str:
    return (FAKE_TODAY - timedelta(days=n)).isoformat()


def url(value: str | None) -> str:
    base = f"/v1/plots/{PLOT_ID}/bucket-suggestion"
    return base if value is None else f"{base}?last_irrigation={value}"


def test_check_order_future_date_422_even_when_upstreams_down(client, fake):
    fake.override("plot", exc=httpx.ConnectError("down"))
    fake.override("forecast", exc=httpx.ConnectError("down"))
    future = (FAKE_TODAY + timedelta(days=3)).isoformat()
    assert_problem(client.get(url(future)), 422, "VALIDATION")
    assert fake.requests == []


@pytest.mark.parametrize("value", ["2031-13-40", "2026-02-31", "abc", "", "2031-6-1", None])
def test_check_order_invalid_format_422_before_upstream(client, fake, value):
    assert_problem(client.get(url(value)), 422, "VALIDATION")
    assert fake.requests == []


def test_check_order_unknown_plot_404_with_valid_date(client, fake):
    response = client.get(f"/v1/plots/no-such-plot/bucket-suggestion?last_irrigation={days_back(3)}")
    assert_problem(response, 404, "NOT_FOUND")


def test_check_order_registry_down_503(client, fake):
    fake.override("plot", exc=httpx.ConnectError("down"))
    body = assert_problem(client.get(url(days_back(3))), 503, "UPSTREAM_UNAVAILABLE")
    assert REGISTRY in body["detail"]


def test_check_order_weather_down_503_never_zeros(client, fake):
    fake.override("forecast", exc=httpx.ConnectError("down"))
    response = client.get(url(days_back(3)))
    body = assert_problem(response, 503, "UPSTREAM_UNAVAILABLE")
    assert WEATHER in body["detail"]
    assert "suggestion" not in body


def test_check_order_weather_down_503_even_when_season_ended(client, fake):
    fake.bodies["plot"]["planting_date"] = planted(200)
    fake.override("forecast", exc=httpx.ConnectError("down"))
    body = assert_problem(client.get(url(days_back(3))), 503, "UPSTREAM_UNAVAILABLE")
    assert WEATHER in body["detail"]


def test_check_order_season_ended_wins(client, fake):
    fake.bodies["plot"]["planting_date"] = planted(200)
    before_planting = (FAKE_TODAY - timedelta(days=210)).isoformat()
    response = client.get(url(before_planting))
    assert response.status_code == 200
    assert response.json() == {
        "plot_id": PLOT_ID,
        "last_irrigation": before_planting,
        "suggestion": None,
        "exact": False,
        "reason": "season_ended",
        "past_days_requested": 0,
        "past_days_returned": 0,
        "stale": False,
    }


def test_check_order_ended_plot_with_future_date_still_422(client, fake):
    fake.bodies["plot"]["planting_date"] = planted(200)
    future = (FAKE_TODAY + timedelta(days=3)).isoformat()
    assert_problem(client.get(url(future)), 422, "VALIDATION")
    assert fake.requests == []


def test_422_before_planting(client, fake):
    fake.bodies["plot"]["planting_date"] = planted(10)
    assert_problem(client.get(url(days_back(12))), 422, "VALIDATION")


def test_422_more_than_92_days_back(client, fake):
    fake.bodies["plot"]["planting_date"] = planted(130)
    assert_problem(client.get(url(days_back(93))), 422, "VALIDATION")


def test_92_days_back_is_allowed(client, fake):
    fake.bodies["plot"]["planting_date"] = planted(130)
    flat(fake)
    response = client.get(url(days_back(92)))
    assert response.status_code == 200
    assert response.json()["past_days_requested"] == 91


def test_422_after_the_points_today(client, fake):
    # Passes step 1 through the UTC+14 margin, fails step 4 against weather's today.
    tomorrow = (FAKE_TODAY + timedelta(days=1)).isoformat()
    assert_problem(client.get(url(tomorrow)), 422, "VALIDATION")
    assert len(fake.calls("forecast")) == 1


def test_today_is_date_after_past_days(client, fake):
    fake.past_returned = 3  # weather has only 3 past days: today is still its 4th date
    flat(fake, et0=20.0)
    response = client.get(url(days_back(5)))  # D = 5 days back: 4 past days needed
    assert response.status_code == 200
    assert response.json()["past_days_requested"] == 4
    assert response.json()["past_days_returned"] == 3
    (request,) = fake.calls("forecast")
    query = parse_qs(request.url.query.decode())
    assert query["days"] == ["1"] and query["past_days"] == ["92"]


def test_emitter_is_not_fetched(client, fake):
    assert client.get(url(days_back(3))).status_code == 200
    assert fake.calls("emitter") == []


@pytest.mark.parametrize("back", [0, 1])
def test_d_yesterday_and_today_give_1_0_with_0_0_days(client, fake, back):
    case4(fake)
    response = client.get(url(days_back(back)))
    assert response.status_code == 200
    body = response.json()
    assert body["suggestion"] == 1.0 and body["exact"] is True and body["reason"] is None
    assert (body["past_days_requested"], body["past_days_returned"]) == (0, 0)


def test_case_4a_through_http(client, fake):
    case4(fake)
    response = client.get(url(days_back(4)))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == BODY_KEYS
    assert body["plot_id"] == PLOT_ID
    assert body["last_irrigation"] == days_back(4)
    assert body["suggestion"] == 0.7031
    assert body["exact"] is True
    assert body["reason"] is None
    assert body["past_days_requested"] == 3
    assert body["past_days_returned"] == 3
    assert body["stale"] is False


def test_case_4b_clamped_to_zero(client, fake):
    case4(fake)
    body = client.get(url(days_back(15))).json()
    assert body["suggestion"] == 0.0
    assert body["exact"] is True
    assert body["past_days_requested"] == 14
    assert body["past_days_returned"] == 14


def test_fewer_past_days_reaching_empty_is_exact(client, fake):
    case4(fake)
    flat(fake, et0=30.0)  # ETc 34.5 a day: empty after two days
    fake.past_returned = 3
    body = client.get(url(days_back(15))).json()
    assert body["suggestion"] == 0.0
    assert body["exact"] is True
    assert body["past_days_requested"] == 14
    assert body["past_days_returned"] == 3


def test_fewer_past_days_not_reaching_empty_is_null(client, fake):
    case4(fake)
    flat(fake, et0=1.0)
    fake.past_returned = 3
    response = client.get(url(days_back(15)))
    assert response.status_code == 200  # P4: a fact, not an error
    body = response.json()
    assert body["suggestion"] is None
    assert body["exact"] is False
    assert body["reason"] == "insufficient_past_weather"
    assert body["past_days_requested"] == 14
    assert body["past_days_returned"] == 3


def test_no_past_days_at_all_is_null(client, fake):
    case4(fake)
    fake.past_returned = 0
    body = client.get(url(days_back(5))).json()
    assert body["suggestion"] is None
    assert body["reason"] == "insufficient_past_weather"
    assert body["past_days_returned"] == 0


def test_only_the_last_needed_past_days_are_used(client, fake):
    # 92 past days come back, only the last 3 count: the early huge ET0 must not matter.
    case4(fake)

    def edit(body):
        for n, d in enumerate(body["days"]):
            d["et0_mm"], d["rain_mm"] = (50.0 if n < 80 else 5.0), 0.0

    fake.edit("forecast", edit)
    assert client.get(url(days_back(4))).json()["suggestion"] == 0.7031


def test_suggestion_stale_propagates(client, fake):
    case4(fake)
    fake.edit("forecast", lambda body: body.update(stale=True))
    assert client.get(url(days_back(4))).json()["stale"] is True


def test_unexpected_weather_answer_is_500(client, fake):
    fake.override("forecast", content=b"not json")
    assert_problem(client.get(url(days_back(3))), 500, "INTERNAL")


def test_suggestion_weather_with_one_extra_day_is_500(client, fake):
    case4(fake)

    def extra(body):
        last = date.fromisoformat(body["days"][-1]["date"]) + timedelta(days=1)
        body["days"].append({"date": last.isoformat(), "et0_mm": 5.0, "rain_mm": 0.0})

    fake.edit("forecast", extra)
    assert_problem(client.get(url(days_back(3))), 500, "INTERNAL")


def test_answer_does_not_depend_on_the_clock_only_on_weather_today(client, fake, monkeypatch):
    case4(fake)
    before = client.get(url(days_back(4)))
    assert before.status_code == 200
    # The clock moves 3 days; weather's "today" stays FAKE_TODAY. Still inside the UTC+14 check.
    monkeypatch.setattr(main, "utc_now", lambda: datetime(2031, 6, 4, 12, tzinfo=UTC))
    after = client.get(url(days_back(4)))
    assert after.json() == before.json()
