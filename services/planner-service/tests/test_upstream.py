import os
from datetime import date

import httpx
import pytest

import config
from config import Settings, get_settings
from conftest import SERVICE_KEYS
from engine.crops import UnknownCrop
from engine.plan import DayWeather
from fakes import CROP_ID, EMITTER_ID, FAKE_TODAY, PLOT_ID, SOIL_ID, FakeUpstreams
from upstream import (
    Forecast,
    PlotNotFound,
    PlotRecord,
    UnexpectedUpstream,
    Upstream,
    UpstreamUnavailable,
)

REGISTRY, WEATHER = "registry-service", "weather-service"

pytestmark = pytest.mark.anyio  # anyio's pytest plugin ships with httpx: no new package


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_settings(**kw) -> Settings:
    kw.setdefault("registry_url", "http://registry.invalid")
    kw.setdefault("weather_url", "http://weather.invalid")
    return Settings(_env_file=None, **kw)


@pytest.fixture
def fake():
    return FakeUpstreams()


@pytest.fixture
def make_upstream(fake):
    def make(**settings_kw) -> Upstream:
        return Upstream(httpx.AsyncClient(transport=fake.transport()), make_settings(**settings_kw))

    return make


@pytest.fixture
def up(make_upstream):
    return make_upstream()


# --- isolation -----------------------------------------------------------------

def test_real_env_file_and_inherited_keys_are_ignored(tmp_path, monkeypatch):
    # A `.env` in the working directory (with a key that would be a startup error)
    # must not be read, and no key of this service may be inherited from the shell.
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("REGISTRY_URL=http://leaked.invalid\nNOT_A_KEY=1\n")
    assert not [k for k in SERVICE_KEYS if k in os.environ]
    monkeypatch.setenv("REGISTRY_URL", "http://registry.invalid")
    monkeypatch.setenv("WEATHER_URL", "http://weather.invalid")
    settings = get_settings()
    assert settings.registry_url == "http://registry.invalid"
    assert not config.ENV_FILE.exists()


# --- happy path ----------------------------------------------------------------

async def test_happy_path_parses_plot_soil_emitter_crop_forecast(fake, up):
    assert await up.get_plot(PLOT_ID) == PlotRecord(
        area_m2=1000.0,
        crop_id=CROP_ID,
        planting_date=date(2031, 4, 13),
        soil_id=SOIL_ID,
        row_spacing_m=1.5,
        emitter_spacing_m=0.4,
        emitter_id=EMITTER_ID,
        lat=31.25,
        lon=34.79,
    )
    assert await up.get_soil_water(SOIL_ID) == 83.0
    assert await up.get_flow_lph(EMITTER_ID) == 1.6
    assert await up.check_crop(CROP_ID) is None

    fc = await up.get_forecast(31.25, 34.79, 3)
    assert isinstance(fc, Forecast)
    assert (fc.past_days_returned, fc.fetched_at, fc.stale) == (0, "2031-06-01T06:00:00Z", False)
    assert fc.days == [
        DayWeather(date(2031, 6, 1), 4.0, 0.0, False),
        DayWeather(date(2031, 6, 2), 4.1, 1.5, False),
        DayWeather(date(2031, 6, 3), 4.2, 0.0, False),
    ]
    assert [r.url.path for r in fake.requests] == [
        f"/v1/plots/{PLOT_ID}",
        f"/v1/soils/{SOIL_ID}",
        f"/v1/emitters/{EMITTER_ID}",
        f"/v1/crops/{CROP_ID}",
        "/v1/forecast",
    ]


async def test_forecast_with_past_days_one_call(fake, up):
    fc = await up.get_forecast(31.25, 34.79, 1, 92)
    (request,) = fake.calls("forecast")
    assert dict(request.url.params) == {"lat": "31.25", "lon": "34.79", "days": "1", "past_days": "92"}
    assert fc.past_days_returned == 92
    assert len(fc.days) == 93
    # "Today" is the day after the past days, from the response, not from a clock.
    assert fc.days[fc.past_days_returned].date == FAKE_TODAY


async def test_forecast_without_past_days_sends_no_past_days_param(fake, up):
    await up.get_forecast(31.25, 34.79, 7)
    (request,) = fake.calls("forecast")
    assert "past_days" not in request.url.params
    assert request.url.params["days"] == "7"


async def test_fewer_past_days_returned_is_accepted(fake, up):
    fake.past_returned = 67
    fc = await up.get_forecast(31.25, 34.79, 1, 92)
    assert fc.past_days_returned == 67
    assert len(fc.days) == 68


async def test_stale_flag_copied_to_every_day(fake, up):
    fake.edit("forecast", lambda b: b.update(stale=True))
    fc = await up.get_forecast(31.25, 34.79, 4)
    assert fc.stale is True
    assert [d.stale for d in fc.days] == [True] * 4


async def test_plot_id_is_one_path_segment(fake, up):
    with pytest.raises(PlotNotFound):
        await up.get_plot("x/../../v1/farms")
    assert fake.requests[0].url.raw_path.startswith(b"/v1/plots/x%2F")


# --- failures: unavailable -----------------------------------------------------

REGISTRY_CALLS = {
    "plot": ("plot", lambda u: u.get_plot(PLOT_ID)),
    "soil": ("soil", lambda u: u.get_soil_water(SOIL_ID)),
    "emitter": ("emitter", lambda u: u.get_flow_lph(EMITTER_ID)),
    "crop": ("crop", lambda u: u.check_crop(CROP_ID)),
}
FORECAST_CALL = ("forecast", lambda u: u.get_forecast(31.25, 34.79, 1, 92))
ALL_CALLS = {**REGISTRY_CALLS, "forecast": FORECAST_CALL}


def service_of(name: str) -> str:
    return WEATHER if name == "forecast" else REGISTRY


@pytest.mark.parametrize("name", ALL_CALLS)
@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_5xx_is_unavailable(fake, up, name, status):
    route, call = ALL_CALLS[name]
    fake.override(route, status=status)
    with pytest.raises(UpstreamUnavailable) as exc:
        await call(up)
    assert exc.value.service == service_of(name)


@pytest.mark.parametrize("name", ALL_CALLS)
@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
async def test_connection_error_is_unavailable(fake, up, name, error):
    route, call = ALL_CALLS[name]
    fake.override(route, exc=error)
    with pytest.raises(UpstreamUnavailable) as exc:
        await call(up)
    assert exc.value.service == service_of(name)


@pytest.mark.parametrize("name", REGISTRY_CALLS)
async def test_registry_timeout_names_registry(fake, make_upstream, name):
    route, call = REGISTRY_CALLS[name]
    fake.override(route, delay=1)
    with pytest.raises(UpstreamUnavailable) as exc:
        await call(make_upstream(registry_timeout_seconds=0.05))
    assert exc.value.service == REGISTRY


async def test_weather_timeout_names_weather(fake, make_upstream):
    fake.override("forecast", delay=1)
    with pytest.raises(UpstreamUnavailable) as exc:
        await FORECAST_CALL[1](make_upstream(weather_timeout_seconds=0.05))
    assert exc.value.service == WEATHER


async def test_whole_call_timeout_on_slow_body(fake, make_upstream):
    # Each chunk arrives in time (per-phase timeouts would pass); the whole call does not.
    fake.override("plot", slow_body=0.02)
    with pytest.raises(UpstreamUnavailable) as exc:
        await make_upstream(registry_timeout_seconds=0.1).get_plot(PLOT_ID)
    assert exc.value.service == REGISTRY
    fake.override("forecast", slow_body=0.02)
    with pytest.raises(UpstreamUnavailable) as exc:
        await make_upstream(weather_timeout_seconds=0.1).get_forecast(31.25, 34.79, 7)
    assert exc.value.service == WEATHER


async def test_slow_but_in_time_answer_passes(fake, make_upstream):
    fake.override("plot", delay=0.02)
    assert (await make_upstream(registry_timeout_seconds=2).get_plot(PLOT_ID)).crop_id == CROP_ID


@pytest.mark.parametrize(
    "header, expected",
    [("7", 7), ("1", 1), (None, 9), ("abc", 9), ("0", 9), ("-3", 9), ("1.5", 9), ("", 9)],
)
async def test_weather_retry_after(fake, make_upstream, header, expected):
    fake.override("forecast", status=503, headers={"Retry-After": header} if header is not None else None)
    with pytest.raises(UpstreamUnavailable) as exc:
        await make_upstream(retry_after_seconds=9).get_forecast(31.25, 34.79, 1)
    assert exc.value.retry_after == expected


@pytest.mark.parametrize("header, expected", [("3600", 3600), ("3601", 3600), ("999999999", 3600)])
async def test_weather_retry_after_is_capped_at_one_hour(fake, make_upstream, header, expected):
    fake.override("forecast", status=503, headers={"Retry-After": header})
    with pytest.raises(UpstreamUnavailable) as exc:
        await make_upstream(retry_after_seconds=9).get_forecast(31.25, 34.79, 1)
    assert exc.value.retry_after == expected


async def test_registry_unavailable_uses_default_retry_after(fake, make_upstream):
    fake.override("plot", status=503, headers={"Retry-After": "30"})
    with pytest.raises(UpstreamUnavailable) as exc:
        await make_upstream(retry_after_seconds=9).get_plot(PLOT_ID)
    assert exc.value.retry_after == 9  # only the weather's own value is passed on


@pytest.mark.parametrize("name", ALL_CALLS)
@pytest.mark.parametrize("failure", [{"status": 503}, {"exc": httpx.ConnectError("x")}])
async def test_no_retries(fake, up, name, failure):
    route, call = ALL_CALLS[name]
    fake.override(route, **failure)
    with pytest.raises(UpstreamUnavailable):
        await call(up)
    assert len(fake.requests) == 1


# --- failures: not found / unexpected -------------------------------------------

async def test_plot_404_is_plot_not_found(fake, up):
    with pytest.raises(PlotNotFound):
        await up.get_plot("00000000-0000-4000-8000-000000000000")


@pytest.mark.parametrize("name", ["soil", "emitter", "crop"])
async def test_soil_emitter_crop_404_is_unexpected(up, name):
    up_call = {
        "soil": lambda: up.get_soil_water("nope"),
        "emitter": lambda: up.get_flow_lph("nope"),
        "crop": lambda: up.check_crop("nope"),
    }[name]
    with pytest.raises(UnexpectedUpstream):
        await up_call()


async def test_crop_known_to_registry_but_without_coefficients(fake, up):
    # P9: the registry has the crop, the planner has no coefficients for it.
    fake.known["crop"] = "wheat"
    with pytest.raises(UnknownCrop):
        await up.check_crop("wheat")


def drop(key):
    return lambda b: b.pop(key)


def put(**kw):
    return lambda b: b.update(kw)


def day(index, **kw):
    return lambda b: b["days"][index].update(kw)


def drop_day_key(index, key):
    return lambda b: b["days"][index].pop(key)


def delete_day(index):
    return lambda b: b["days"].pop(index)


def clash(b):
    b["days"][1]["date"] = b["days"][0]["date"]


NAN = float("nan")

PLOT_CASES = [
    ("area 0", put(area_m2=0)),
    ("area -1", put(area_m2=-1)),
    ("area NaN", put(area_m2=NAN)),
    ("area string", put(area_m2="1000")),
    ("area bool", put(area_m2=True)),
    ("area null", put(area_m2=None)),
    ("row spacing 0", put(row_spacing_m=0)),
    ("emitter spacing -1", put(emitter_spacing_m=-1)),
    ("missing crop_id", drop("crop_id")),
    ("crop_id number", put(crop_id=5)),
    ("missing planting_date", drop("planting_date")),
    ("planting_date not ISO", put(planting_date="13/04/2031")),
    ("planting_date number", put(planting_date=20310413)),
    ("lat NaN", put(lat=NAN)),
    ("lon string", put(lon="34.79")),
    ("missing soil_id", drop("soil_id")),
    ("missing emitter_id", drop("emitter_id")),
]


@pytest.mark.parametrize("edit", [c[1] for c in PLOT_CASES], ids=[c[0] for c in PLOT_CASES])
async def test_bad_plot_is_unexpected(fake, up, edit):
    fake.edit("plot", edit)
    with pytest.raises(UnexpectedUpstream):
        await up.get_plot(PLOT_ID)


@pytest.mark.parametrize(
    "edit",
    [put(available_water_mm_per_m=0), put(available_water_mm_per_m=-5), put(available_water_mm_per_m="83"),
     put(available_water_mm_per_m=None), put(available_water_mm_per_m=True), drop("available_water_mm_per_m")],
)
async def test_bad_soil_is_unexpected(fake, up, edit):
    fake.edit("soil", edit)
    with pytest.raises(UnexpectedUpstream):
        await up.get_soil_water(SOIL_ID)


@pytest.mark.parametrize(
    "edit", [put(flow_lph=0), put(flow_lph=-1.6), put(flow_lph=NAN), put(flow_lph="1.6"), drop("flow_lph")]
)
async def test_bad_emitter_is_unexpected(fake, up, edit):
    fake.edit("emitter", edit)
    with pytest.raises(UnexpectedUpstream):
        await up.get_flow_lph(EMITTER_ID)


@pytest.mark.parametrize("name", ALL_CALLS)
@pytest.mark.parametrize(
    "content", [b"{not json", b"", b"[]", b"[1, 2]", b"null", b'"text"', b"\xff\xfe"],
    ids=["invalid", "empty", "array", "array2", "null", "string", "binary"],
)
async def test_bad_json_is_unexpected(fake, up, name, content):
    route, call = ALL_CALLS[name]
    fake.override(route, content=content)
    with pytest.raises(UnexpectedUpstream):
        await call(up)


@pytest.mark.parametrize("name", ALL_CALLS)
@pytest.mark.parametrize("status", [400, 401, 403, 422, 429])
async def test_other_4xx_is_unexpected(fake, up, name, status):
    route, call = ALL_CALLS[name]
    fake.override(route, status=status)
    with pytest.raises(UnexpectedUpstream):
        await call(up)


async def test_weather_404_and_registry_redirect_are_unexpected(fake, up):
    fake.override("forecast", status=404)
    with pytest.raises(UnexpectedUpstream):
        await up.get_forecast(31.25, 34.79, 1)
    fake.override("plot", status=302, headers={"Location": "/elsewhere"})
    with pytest.raises(UnexpectedUpstream):
        await up.get_plot(PLOT_ID)


FORECAST_CASES = [
    ("null et0 is not zero", day(0, et0_mm=None)),
    ("missing et0", drop_day_key(0, "et0_mm")),
    ("negative et0", day(0, et0_mm=-0.1)),
    ("NaN et0", day(0, et0_mm=NAN)),
    ("inf et0", day(0, et0_mm=float("inf"))),
    ("string et0", day(0, et0_mm="4.0")),
    ("bool et0", day(0, et0_mm=True)),
    ("missing rain", drop_day_key(1, "rain_mm")),
    ("null rain is not zero", day(1, rain_mm=None)),
    ("negative rain", day(1, rain_mm=-1)),
    ("NaN rain", day(1, rain_mm=NAN)),
    ("one day short", delete_day(-1)),
    ("one day too many", lambda b: b["days"].append(dict(b["days"][-1], date="2031-06-30"))),
    ("duplicate date", clash),
    ("gapped date", day(2, date="2031-06-05")),
    ("date not ISO", day(0, date="2031/06/01")),
    ("date missing", drop_day_key(0, "date")),
    ("date number", day(0, date=20310601)),
    ("days missing", drop("days")),
    ("days not a list", put(days="x")),
    ("day not an object", lambda b: b["days"].__setitem__(0, 5)),
    ("stale missing", drop("stale")),
    ("stale string", put(stale="false")),
    ("fetched_at missing", drop("fetched_at")),
    ("fetched_at number", put(fetched_at=5)),
]


@pytest.mark.parametrize("edit", [c[1] for c in FORECAST_CASES], ids=[c[0] for c in FORECAST_CASES])
async def test_bad_forecast_is_unexpected(fake, up, edit):
    fake.edit("forecast", edit)
    with pytest.raises(UnexpectedUpstream):
        await up.get_forecast(31.25, 34.79, 3)


@pytest.mark.parametrize(
    "edit",
    [put(past_days_returned=93), put(past_days_returned=-1), put(past_days_returned="2"),
     put(past_days_returned=None), put(past_days_returned=True), drop("past_days_returned")],
)
async def test_bad_past_days_returned_is_unexpected(fake, up, edit):
    fake.edit("forecast", edit)
    with pytest.raises(UnexpectedUpstream):
        await up.get_forecast(31.25, 34.79, 1, 92)


async def test_past_days_returned_without_asking_is_unexpected(fake, up):
    fake.edit("forecast", put(past_days_returned=2))
    with pytest.raises(UnexpectedUpstream):
        await up.get_forecast(31.25, 34.79, 1)
