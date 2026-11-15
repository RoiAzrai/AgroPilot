from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from config import Settings
from forecasts import Answer, ForecastCache, Unavailable
from provider import Day, Forecast, ProviderError
from tests.fakes import FakeClock, ScriptedFetch

UTC = timezone.utc
CELL = (319, 348)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def settings() -> Settings:
    return Settings(provider_base_url="http://provider.invalid/v1/forecast", _env_file=None)


def make_forecast(first: date, fetched_at: datetime, n: int = 8, tz: str = "Asia/Jerusalem"):
    days = tuple(Day(first + timedelta(days=i), 5.0 + i, float(i)) for i in range(n))
    return Forecast(days=days, fetched_at=fetched_at, timezone_name=tz)


T0 = datetime(2026, 11, 15, 8, 0, tzinfo=UTC)  # 10:00 in Jerusalem


def setup(fetch_items, start=T0):
    clock = FakeClock(start)
    fetch = ScriptedFetch(*fetch_items)
    return ForecastCache(fetch, settings(), clock.now), fetch, clock


def good(at=T0, **kw):
    return make_forecast(date(2026, 11, 15), at, **kw)


@pytest.mark.anyio
async def test_first_request_fetches():
    cache, fetch, _ = setup([good()])
    a = await cache.get(CELL, 7)
    assert fetch.calls == 1
    assert isinstance(a, Answer)
    assert a.stale is False
    assert a.fetched_at == T0
    assert len(a.days) == 7
    assert a.days[0].date == date(2026, 11, 15)


@pytest.mark.anyio
async def test_fresh_served_without_fetch():
    cache, fetch, clock = setup([good()])
    await cache.get(CELL, 7)
    clock.advance(2 * 3600 + 59 * 60)
    a = await cache.get(CELL, 7)
    assert fetch.calls == 1
    assert a.stale is False


@pytest.mark.anyio
async def test_expired_refetches():
    cache, fetch, clock = setup([good(), good(T0 + timedelta(hours=3, minutes=1))])
    await cache.get(CELL, 7)
    clock.advance(3 * 3600 + 60)
    a = await cache.get(CELL, 7)
    assert fetch.calls == 2
    assert a.stale is False


@pytest.mark.anyio
async def test_failure_serves_stale_within_24h():
    cache, fetch, clock = setup([good(), ProviderError("down")])
    await cache.get(CELL, 7)
    clock.advance(23 * 3600)
    a = await cache.get(CELL, 7)
    assert fetch.calls == 2
    assert a.stale is True
    assert a.fetched_at == T0


@pytest.mark.anyio
async def test_failure_after_24h_is_unavailable():
    cache, _, clock = setup([good(), ProviderError("down")])
    await cache.get(CELL, 7)
    clock.advance(25 * 3600)
    with pytest.raises(Unavailable) as exc:
        await cache.get(CELL, 7)
    assert exc.value.retry_after == 5


@pytest.mark.anyio
async def test_failure_without_forecast_is_unavailable():
    cache, _, _ = setup([ProviderError("down")])
    with pytest.raises(Unavailable) as exc:
        await cache.get(CELL, 7)
    assert exc.value.retry_after == 5


@pytest.mark.anyio
async def test_fresh_forecast_after_local_midnight_still_has_seven_days():
    # fetched 23:00 Jerusalem (21:00 UTC) on 15 Nov; asked 01:00 on 16 Nov.
    fetched = datetime(2026, 11, 15, 21, 0, tzinfo=UTC)
    cache, fetch, clock = setup([good(fetched)], start=fetched)
    await cache.get(CELL, 7)
    clock.advance(2 * 3600)
    a = await cache.get(CELL, 7)
    assert fetch.calls == 1
    assert len(a.days) == 7
    assert a.days[0].date == date(2026, 11, 16)


@pytest.mark.anyio
async def test_today_missing_is_unavailable():
    cache, _, _ = setup([make_forecast(date(2026, 11, 16), T0)])
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)


@pytest.mark.anyio
async def test_fewer_days_than_requested_is_unavailable():
    cache, _, _ = setup([good(n=6)])
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)


@pytest.mark.anyio
async def test_utc_plus_14_zone():
    # 11:00 UTC on 15 Nov is 01:00 on 16 Nov in Kiritimati.
    now = datetime(2026, 11, 15, 11, 0, tzinfo=UTC)
    assert now.astimezone(ZoneInfo("Pacific/Kiritimati")).date() == date(2026, 11, 16)
    cache, _, _ = setup(
        [make_forecast(date(2026, 11, 16), now, tz="Pacific/Kiritimati")], start=now
    )
    a = await cache.get(CELL, 7)
    assert a.days[0].date == date(2026, 11, 16)


@pytest.mark.anyio
async def test_dst_change_uses_zone_name():
    # Fetched 2026-11-01 05:00 UTC = 01:00 EDT, before the 06:00 UTC DST end.
    # Asked 2026-11-02 04:59 UTC = 23:59 EST on 1 Nov. An offset kept from
    # fetch time (-4 h) would give 00:59 on 2 Nov.
    fetched = datetime(2026, 11, 1, 5, 0, tzinfo=UTC)
    fc = make_forecast(date(2026, 11, 1), fetched, tz="America/New_York")
    cache, fetch, clock = setup([fc, ProviderError("down")], start=fetched)
    await cache.get(CELL, 7)
    clock.advance(23 * 3600 + 59 * 60)
    assert clock.now() == datetime(2026, 11, 2, 4, 59, tzinfo=UTC)
    a = await cache.get(CELL, 7)
    assert fetch.calls == 2
    assert a.stale is True
    assert a.fetched_at == fetched
    assert a.days[0].date == date(2026, 11, 1)


@pytest.mark.anyio
async def test_age_exactly_fresh_seconds_refetches():
    cache, fetch, clock = setup([good(), good()])
    await cache.get(CELL, 7)
    clock.advance(10800)
    await cache.get(CELL, 7)
    assert fetch.calls == 2


@pytest.mark.anyio
async def test_age_exactly_max_stale_is_still_served():
    cache, _, clock = setup([good(), ProviderError("down")])
    await cache.get(CELL, 7)
    clock.advance(86400)
    a = await cache.get(CELL, 7)
    assert a.stale is True
    assert a.fetched_at == T0


@pytest.mark.anyio
@pytest.mark.parametrize("n", range(1, 8))
async def test_slices_days(n):
    fc = good()
    cache, _, _ = setup([fc])
    a = await cache.get(CELL, n)
    assert a.days == list(fc.days[:n])
    assert len(a.days) == n
    assert a.days[0].date == date(2026, 11, 15)


@pytest.mark.anyio
async def test_cells_are_independent():
    cache, fetch, _ = setup([good()])
    await cache.get((1, 1), 7)
    await cache.get((2, 2), 7)
    await cache.get((1, 1), 7)
    assert fetch.calls == 2
    assert fetch.cells == [(1, 1), (2, 2)]
