import asyncio
import json
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from conftest import assert_problem
from fakes import FAKE_TODAY, PLOT_ID, FakeUpstreams

REGISTRY, WEATHER = "registry-service", "weather-service"
DAY_KEYS = {
    "date", "stage", "et0_mm", "rain_mm", "kc", "litres", "run_minutes",
    "bucket_mm", "bucket_capacity_mm", "stale",
}
TOP_KEYS = {"plot_id", "crop", "bucket_start", "fetched_at", "stale", "days"}


@pytest.fixture
def fake():
    return FakeUpstreams()


def planted(season_day: int) -> str:
    """Planting date that makes FAKE_TODAY season day `season_day`."""
    return (FAKE_TODAY - timedelta(days=season_day - 1)).isoformat()


def case1(fake: FakeUpstreams) -> None:
    """Cases.md case 1: tomato, sand, season day 80, ET0 5.0, no rain."""
    fake.bodies["plot"]["planting_date"] = planted(80)

    def flat(body):
        for d in body["days"]:
            d["et0_mm"], d["rain_mm"] = 5.0, 0.0

    fake.edit("forecast", flat)


def case5(fake: FakeUpstreams) -> None:
    """Cases.md case 5: loam, flow 1.0, season day 80, ET0 6.0, no rain."""
    fake.bodies["plot"]["planting_date"] = planted(80)
    fake.bodies["soil"]["available_water_mm_per_m"] = 175
    fake.bodies["emitter"]["flow_lph"] = 1.0

    def flat(body):
        for d in body["days"]:
            d["et0_mm"], d["rain_mm"] = 6.0, 0.0

    fake.edit("forecast", flat)


def plan_url(**params) -> str:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"/v1/plots/{PLOT_ID}/plan" + (f"?{query}" if query else "")


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_plan_200_shape_case1(client, fake):
    case1(fake)
    response = client.get(plan_url())
    assert response.status_code == 200
    body = response.json()
    assert set(body) == TOP_KEYS
    assert body["plot_id"] == PLOT_ID
    assert body["crop"] == "tomato"
    assert body["bucket_start"] == 1.0
    assert body["fetched_at"] == "2031-06-01T06:00:00Z"
    assert body["stale"] is False
    assert len(body["days"]) == 7
    assert all(set(d) == DAY_KEYS for d in body["days"])
    first = body["days"][0]
    assert first == {
        "date": "2031-06-01", "stage": "mid", "et0_mm": 5.0, "rain_mm": 0.0, "kc": 1.15,
        "litres": 0, "run_minutes": 0, "bucket_mm": 52.35, "bucket_capacity_mm": 58.1,
        "stale": False,
    }
    assert [d["bucket_mm"] for d in body["days"]] == [
        52.35, 46.6, 40.85, 35.1, 58.1, 52.35, 46.6,
    ]
    assert body["days"][4]["run_minutes"] == 647
    assert body["days"][4]["litres"] == 28750


def test_p11_cap_through_http_case5(client, fake):
    case5(fake)
    body = client.get(plan_url(bucket_start=0.7)).json()
    assert body["bucket_start"] == 0.7
    assert [d["run_minutes"] for d in body["days"]] == [0, 1440, 628, 0, 0, 0, 0]
    assert [d["litres"] for d in body["days"]] == [0, 40000, 17450, 0, 0, 0, 0]
    assert [d["bucket_mm"] for d in body["days"]][:3] == [78.85, 111.95, 122.5]


def test_defaults_days_7_bucket_start_1(client, fake):
    case1(fake)
    client.get(plan_url())
    assert fake.calls("forecast")[0].url.params["days"] == "7"
    assert "past_days" not in fake.calls("forecast")[0].url.params


def test_days_param_goes_to_weather_and_sets_length(client, fake):
    case1(fake)
    body = client.get(plan_url(days=3)).json()
    assert fake.calls("forecast")[0].url.params["days"] == "3"
    assert len(body["days"]) == 3


def test_dates_come_from_weather(client, fake):
    case1(fake)

    def shift(body):
        for n, d in enumerate(body["days"]):
            d["date"] = f"2031-03-{1 + n:02d}"

    fake.edit("forecast", shift)
    fake.bodies["plot"]["planting_date"] = "2031-01-01"
    body = client.get(plan_url(days=5)).json()
    assert [d["date"] for d in body["days"]] == [f"2031-03-{n:02d}" for n in range(1, 6)]
    assert body["days"][0]["stage"] == "dev"  # season day 60, from weather's date


def test_stale_forecast_marks_every_day(client, fake):
    case1(fake)

    def stale(body):
        body["stale"] = True
        body["fetched_at"] = "2031-05-31T22:00:00Z"
        for d in body["days"]:
            d["et0_mm"], d["rain_mm"] = 5.0, 0.0

    fake.edit("forecast", stale)
    body = client.get(plan_url()).json()
    assert body["stale"] is True
    assert body["fetched_at"] == "2031-05-31T22:00:00Z"
    assert [d["stale"] for d in body["days"]] == [True] * 7


@pytest.mark.parametrize("days", ["0", "8", "abc", "-1", "2.5"])
def test_422_bad_days(client, fake, days):
    assert_problem(client.get(plan_url(days=days)), 422, "VALIDATION")
    assert fake.requests == []


@pytest.mark.parametrize("value", ["-0.1", "1.1", "abc", "nan", "inf", "-inf"])
def test_422_bad_bucket_start(client, fake, value):
    assert_problem(client.get(plan_url(bucket_start=value)), 422, "VALIDATION")
    assert fake.requests == []


@pytest.mark.parametrize("value", ["0", "1", "0.5"])
def test_bucket_start_edges_accepted(client, fake, value):
    case1(fake)
    assert client.get(plan_url(bucket_start=value)).status_code == 200


def test_unknown_crop_is_422_with_data_problem_detail(client, fake):
    fake.bodies["plot"]["crop_id"] = "wheat"
    fake.known["crop"] = "wheat"
    body = assert_problem(client.get(plan_url()), 422, "VALIDATION")
    assert "no irrigation coefficients" in body["detail"]
    assert "data problem" in body["detail"]


def test_plot_404_is_404_not_found(client, fake):
    response = client.get("/v1/plots/no-such-plot/plan")
    assert_problem(response, 404, "NOT_FOUND")
    assert fake.calls("soil") == [] and fake.calls("forecast") == []


def test_unknown_route_404(client):
    assert_problem(client.get("/v1/nothing"), 404, "NOT_FOUND")


def test_wrong_method_405_validation(client):
    assert_problem(client.post(plan_url()), 405, "VALIDATION")


FAILURES = {
    "connection": dict(exc=httpx.ConnectError("boom")),
    "timeout": dict(exc=httpx.ReadTimeout("slow")),
    "500": dict(status=500, content=b"oops"),
    "503": dict(status=503, content=b"", headers={"Retry-After": "9"}),
}


@pytest.mark.parametrize("failure", FAILURES)
@pytest.mark.parametrize(
    "route, service", [("plot", REGISTRY), ("soil", REGISTRY), ("emitter", REGISTRY),
                       ("crop", REGISTRY), ("forecast", WEATHER)],
)
def test_upstream_failure_never_a_plan(client, fake, route, service, failure):
    case1(fake)
    fake.override(route, **FAILURES[failure])
    response = client.get(plan_url())
    body = assert_problem(response, 503, "UPSTREAM_UNAVAILABLE")
    assert body["detail"] == f"{service} is unavailable"
    expected = "9" if service == WEATHER and failure == "503" else "5"
    assert response.headers["retry-after"] == expected
    assert "days" not in body


UNEXPECTED = {
    "bad json from weather": ("forecast", dict(content=b"not json")),
    "soil 404": ("soil", dict(status=404, content=b'{"code":"NOT_FOUND"}')),
    "registry 400": ("emitter", dict(status=400, content=b"{}")),
}


@pytest.mark.parametrize("name", UNEXPECTED)
def test_unexpected_upstream_is_500_internal_without_details(client, fake, name):
    route, kwargs = UNEXPECTED[name]
    fake.override(route, **kwargs)
    response = client.get(plan_url())
    body = assert_problem(response, 500, "INTERNAL")
    assert body["detail"] == "Internal server error"
    assert "days" not in body and "not json" not in json.dumps(body)


def test_wrong_day_count_is_500_internal(client, fake):
    fake.edit("forecast", lambda body: body["days"].pop())
    assert_problem(client.get(plan_url()), 500, "INTERNAL")


def test_a_bug_is_500_internal_not_unavailable(client, fake, monkeypatch):
    def broken(*args, **kwargs):
        raise ZeroDivisionError("secret internal detail")

    monkeypatch.setattr(main, "build_plan", broken)
    response = client.get(plan_url())
    body = assert_problem(response, 500, "INTERNAL")
    assert "secret" not in json.dumps(body)


def test_ended_season_plan(client, fake):
    fake.bodies["plot"]["planting_date"] = "2031-01-01"  # season 135 days: over by June
    body_days = client.get(plan_url()).json()["days"]
    assert len(body_days) == 7
    for day in body_days:
        assert day["stage"] == "ended"
        assert day["litres"] == 0 and day["run_minutes"] == 0
        assert day["kc"] is None and day["bucket_mm"] is None
        assert day["bucket_capacity_mm"] is None
        assert day["et0_mm"] > 0 and day["stale"] is False


def test_problem_json_content_type_and_exact_keys(client):
    assert_problem(client.get(plan_url(days=0)), 422, "VALIDATION")


class OrderedFake(FakeUpstreams):
    """Every route but the plot waits at a barrier of 4: it opens only when soil, emitter,
    crop and forecast are all in flight at once. Serial calls hit the 1 s wait and fail."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, str]] = []
        self.barrier: asyncio.Barrier | None = None

    async def handler(self, request: httpx.Request) -> httpx.Response:
        name = next(n for n, p in main_routes().items() if p.match(request.url.path))
        self.events.append((name, "start"))
        if name != "plot":
            self.barrier = self.barrier or asyncio.Barrier(4)
            async with asyncio.timeout(1):
                await self.barrier.wait()
        response = await super().handler(request)
        self.events.append((name, "end"))
        return response


def main_routes():
    from fakes import ROUTES

    return ROUTES


def test_parallel_calls_after_the_plot(monkeypatch):
    fake = OrderedFake()
    case1(fake)
    monkeypatch.setenv("REGISTRY_URL", "http://registry.invalid")
    monkeypatch.setenv("WEATHER_URL", "http://weather.invalid")
    monkeypatch.setattr(
        main, "make_client", lambda: httpx.AsyncClient(transport=fake.transport())
    )
    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.get(plan_url())
    assert response.status_code == 200
    started = [name for name, what in fake.events if what == "start"]
    assert started[0] == "plot"
    assert sorted(started[1:]) == ["crop", "emitter", "forecast", "soil"]
    assert fake.events.index(("plot", "end")) < fake.events.index((started[1], "start"))


def test_invalid_settings_fail_the_start(monkeypatch):
    monkeypatch.setenv("WEATHER_URL", "http://weather.invalid")  # REGISTRY_URL is missing
    with pytest.raises(RuntimeError, match="REGISTRY_URL"):
        with TestClient(main.app):
            pass


def test_http_client_has_no_httpx_timeout_so_asyncio_timeout_is_the_only_bound():
    async def build():
        async with main.make_client() as client:
            return client.timeout

    assert asyncio.run(build()) == httpx.Timeout(None)  # httpx's default is a 5 s cut-off


def _one_extra_day(body):
    last = body["days"][-1]["date"]
    day = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
    body["days"].append({"date": day, "et0_mm": 4.0, "rain_mm": 0.0})


def test_plan_weather_with_one_extra_day_is_500(client, fake):
    case1(fake)
    fake.edit("forecast", _one_extra_day)
    assert_problem(client.get(plan_url()), 500, "INTERNAL")
