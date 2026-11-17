import logging
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
    return Settings(
        provider_base_url="http://provider.invalid/v1/forecast",
        provider_retries=0,
        provider_retry_backoff_seconds=0,
        _env_file=None,
    )


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
    assert exc.value.retry_after == 60


@pytest.mark.anyio
async def test_failure_without_forecast_is_unavailable():
    cache, _, _ = setup([ProviderError("down")])
    with pytest.raises(Unavailable) as exc:
        await cache.get(CELL, 7)
    assert exc.value.retry_after == 60


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


# --- past_days (W20-W22, W27) ---

TODAY = date(2026, 11, 15)


def with_past(at=T0, past=92, today=TODAY, **kw):
    """`past` days before `today`, then today and 7 more (the provider's 100 days)."""
    return make_forecast(today - timedelta(days=past), at, n=past + 8, **kw)


def no_past(at=T0):
    """W27: yesterday was invalid, so the entry holds no past days at all."""
    return good(at)


@pytest.mark.anyio
async def test_past_days_window_starts_before_today():
    fc = with_past()
    cache, _, _ = setup([fc])
    a = await cache.get(CELL, 7, past_days=3)
    assert [d.date for d in a.days] == [TODAY + timedelta(days=i) for i in range(-3, 7)]
    assert a.days == list(fc.days[89:99])
    assert a.stale is False
    assert a.past_days_returned == 3


@pytest.mark.anyio
async def test_past_days_zero_is_the_forecast_only():
    fc = with_past()
    cache, _, _ = setup([fc])
    a = await cache.get(CELL, 7, past_days=0)
    assert a.days == list(fc.days[92:99])
    assert a.past_days_returned == 0
    assert a == await cache.get(CELL, 7)


@pytest.mark.anyio
async def test_day_old_stale_entry_still_serves_92_past_days():
    fc = with_past()
    cache, _, clock = setup([fc, ProviderError("down")])
    await cache.get(CELL, 7)
    clock.advance(86400)  # local today is now 16 Nov; the entry has 93 past days
    a = await cache.get(CELL, 7, past_days=92)
    assert a.stale is True
    tomorrow = TODAY + timedelta(days=1)
    assert [d.date for d in a.days] == [tomorrow + timedelta(days=i) for i in range(-92, 7)]
    assert a.days == list(fc.days[1:100])
    assert a.past_days_returned == 92


def short_forecast(at=T0, past=3):
    """`past` days before today, then only 6 days from today: day 7 is missing."""
    return make_forecast(TODAY - timedelta(days=past), at, n=past + 6)


@pytest.mark.anyio
async def test_missing_forecast_day_in_window_is_unavailable():
    cache, _, _ = setup([short_forecast()])
    with pytest.raises(Unavailable) as exc:
        await cache.get(CELL, 7, past_days=3)
    assert exc.value.retry_after == 5


@pytest.mark.anyio
async def test_missing_forecast_day_in_window_on_stale_path_keeps_retry_after():
    cache, _, clock = setup([short_forecast(), ProviderError("down")])
    await cache.get(CELL, 6)
    clock.advance(4 * 3600)
    with pytest.raises(Unavailable) as exc:
        await cache.get(CELL, 7, past_days=3)
    assert exc.value.retry_after == 60


@pytest.mark.anyio
async def test_fewer_past_days_than_asked_serves_the_ones_that_exist():
    fc = with_past(past=67)
    cache, fetch, _ = setup([fc])
    a = await cache.get(CELL, 7, past_days=3)
    assert a.past_days_returned == 3
    assert [d.date for d in a.days] == [TODAY + timedelta(days=i) for i in range(-3, 7)]
    a = await cache.get(CELL, 7, past_days=80)
    assert a.stale is False
    assert a.past_days_returned == 67
    assert [d.date for d in a.days] == [TODAY + timedelta(days=i) for i in range(-67, 7)]
    assert a.days == list(fc.days[:74])
    assert fetch.calls == 1


@pytest.mark.anyio
async def test_no_past_days_available_is_a_normal_answer():
    fc = no_past()
    cache, fetch, _ = setup([fc])
    a = await cache.get(CELL, 7, past_days=5)
    assert a.stale is False
    assert a.past_days_returned == 0
    assert a.days == list(fc.days[:7])
    assert fetch.calls == 1


@pytest.mark.anyio
async def test_stale_entry_after_midnight_counts_former_today_as_past():
    fc = with_past(past=67)
    cache, _, clock = setup([fc, ProviderError("down")])
    await cache.get(CELL, 7)
    clock.advance(86400)  # local today is 16 Nov; 15 Nov is now a past day
    a = await cache.get(CELL, 7, past_days=80)
    assert a.stale is True
    assert a.past_days_returned == 68
    tomorrow = TODAY + timedelta(days=1)
    assert [d.date for d in a.days] == [tomorrow + timedelta(days=i) for i in range(-68, 7)]


@pytest.mark.anyio
async def test_no_past_days_with_past_days_is_served_until_the_next_refresh():
    # W27 (replaces W26 for the past): no 503, the entry keeps serving 0 past days.
    cache, fetch, clock = setup([no_past()])
    a = await cache.get(CELL, 7, past_days=1)
    assert a.past_days_returned == 0
    clock.advance(10799.5)
    a = await cache.get(CELL, 7, past_days=1)
    assert a.past_days_returned == 0
    assert len(a.days) == 7
    assert fetch.calls == 1


@pytest.mark.anyio
async def test_no_past_days_during_pause_serves_stale_forecast_days():
    cache, fetch, clock = setup([no_past(), ProviderError("down")])
    await cache.get(CELL, 7)
    clock.advance(4 * 3600)
    a = await cache.get(CELL, 7, past_days=1)
    assert a.stale is True
    assert a.past_days_returned == 0
    assert fetch.calls == 2
    clock.advance(20)
    a = await cache.get(CELL, 7, past_days=1)
    assert a.stale is True
    assert fetch.calls == 2


@pytest.mark.anyio
async def test_no_past_days_does_not_affect_past_days_zero():
    fc = no_past()
    cache, fetch, _ = setup([fc])
    a = await cache.get(CELL, 7)
    assert a.days == list(fc.days[:7])
    assert a.stale is False
    assert fetch.calls == 1


@pytest.mark.anyio
async def test_provider_clock_ahead_serves_today_from_past_part():
    # Q6: 21:59 UTC on 15 Nov is 23:59 in Jerusalem, but the provider already
    # answered for 16 Nov. Today (15 Nov) is in its past part, with its own date.
    # Before past_days this was a 503 (test_today_missing_is_unavailable).
    now = datetime(2026, 11, 15, 21, 59, tzinfo=UTC)
    fc = with_past(now, today=TODAY + timedelta(days=1))
    cache, _, _ = setup([fc], start=now)
    a = await cache.get(CELL, 7)
    assert [d.date for d in a.days] == [TODAY + timedelta(days=i) for i in range(7)]
    assert a.days == list(fc.days[91:98])


@pytest.mark.anyio
async def test_provider_clock_ahead_with_no_past_days_is_unavailable():
    # Q6 needs the past part: without it the entry starts at the provider's
    # today (16 Nov), so local today (15 Nov) is missing -> 503, as before past_days.
    now = datetime(2026, 11, 15, 21, 59, tzinfo=UTC)
    fc = make_forecast(TODAY + timedelta(days=1), now)
    cache, _, _ = setup([fc], start=now)
    with pytest.raises(Unavailable) as exc:
        await cache.get(CELL, 7)
    assert exc.value.retry_after == 5



@pytest.mark.anyio
async def test_refresh_to_entry_without_past():
    later = T0 + timedelta(hours=4)
    cache, fetch, clock = setup([with_past(), no_past(later)])
    assert len((await cache.get(CELL, 7, past_days=1)).days) == 8
    clock.advance(4 * 3600)
    a = await cache.get(CELL, 7)
    assert fetch.calls == 2
    assert a.stale is False
    assert a.fetched_at == later
    assert [d.date for d in a.days] == [TODAY + timedelta(days=i) for i in range(7)]
    a = await cache.get(CELL, 7, past_days=1)
    assert a.past_days_returned == 0
    assert [d.date for d in a.days] == [TODAY + timedelta(days=i) for i in range(7)]


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.anyio
async def test_fewer_past_days_than_asked_logs_debug_only(caplog):
    cache, _, _ = setup([no_past()])
    await cache.get(CELL, 7)
    caplog.clear()
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="forecasts")  # main.py sets it to INFO
    for _ in range(3):
        await cache.get(CELL, 7, past_days=1)
    assert _warnings(caplog) == []
    debug = [r for r in caplog.records if r.name == "forecasts" and r.levelno == logging.DEBUG]
    assert len(debug) == 3


@pytest.mark.anyio
async def test_stale_log_only_when_stale_answer_is_served(caplog):
    cache, _, clock = setup([short_forecast(), ProviderError("down")])
    await cache.get(CELL, 6)
    clock.advance(4 * 3600)
    caplog.clear()
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7, past_days=3)
    assert not any("serving stale" in m for m in _warnings(caplog))
    assert any("no usable forecast" in m for m in _warnings(caplog))
    caplog.clear()
    a = await cache.get(CELL, 6, past_days=3)
    assert a.stale is True
    assert any("serving stale" in m for m in _warnings(caplog))


@pytest.mark.anyio
async def test_provider_clock_ahead_with_limited_past():
    # Q6 + W27: the provider answers for 16 Nov with 67 valid past days; local
    # today (15 Nov) is its yesterday, so 66 past days are before local today.
    now = datetime(2026, 11, 15, 21, 59, tzinfo=UTC)
    fc = with_past(now, past=67, today=TODAY + timedelta(days=1))
    cache, _, _ = setup([fc], start=now)
    a = await cache.get(CELL, 7, past_days=80)
    assert a.past_days_returned == 66
    assert [d.date for d in a.days] == [TODAY + timedelta(days=i) for i in range(-66, 7)]
    assert a.days == list(fc.days[:73])


@pytest.mark.anyio
async def test_stale_entry_after_midnight_with_no_past_returns_former_today():
    fc = no_past()
    cache, _, clock = setup([fc, ProviderError("down")])
    await cache.get(CELL, 7)
    clock.advance(86400)  # local today is 16 Nov; 15 Nov is the only past day
    a = await cache.get(CELL, 7, past_days=5)
    assert a.stale is True
    assert a.past_days_returned == 1
    assert a.days == list(fc.days[:8])
    assert a.days[0].date == TODAY
