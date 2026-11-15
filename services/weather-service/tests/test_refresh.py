import asyncio
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from config import Settings
from forecasts import ForecastCache, Unavailable
from provider import Day, Forecast, ProviderError
from tests.fakes import FakeClock, ScriptedFetch

UTC = timezone.utc
CELL = (319, 348)
T0 = datetime(2026, 11, 15, 8, 0, tzinfo=UTC)  # 10:00 in Jerusalem


@pytest.fixture
def anyio_backend():
    return "asyncio"


def settings(**kw) -> Settings:
    values = {
        "provider_base_url": "http://provider.invalid/v1/forecast",
        "provider_retry_backoff_seconds": 0,
        "refresh_deadline_seconds": 0.5,
    }
    values.update(kw)
    return Settings(**values, _env_file=None)


def good(at=T0):
    days = tuple(Day(date(2026, 11, 15) + timedelta(days=i), 5.0 + i, float(i)) for i in range(8))
    return Forecast(days=days, fetched_at=at, timezone_name="Asia/Jerusalem")


class SlowFetch:
    """Sleeps (real time) before returning the forecast or raising."""

    def __init__(self, delay: float, item):
        self.delay = delay
        self.item = item
        self.calls = 0

    async def __call__(self, cell):
        self.calls += 1
        await asyncio.sleep(self.delay)
        if isinstance(self.item, Exception):
            raise self.item
        return self.item


def make(fetch, start=T0, **kw):
    clock = FakeClock(start)
    return ForecastCache(fetch, settings(**kw), clock.now), clock


async def stale_cache(fetch_after, **kw):
    """A cache holding a forecast fetched at T0, clock moved to T0 + 4 h (not fresh)."""
    first = ScriptedFetch(good())
    clock = FakeClock(T0)
    cache = ForecastCache(first, settings(**kw), clock.now)
    await cache.get(CELL, 7)
    cache._fetch = fetch_after
    clock.advance(4 * 3600)
    return cache, clock


@pytest.mark.anyio
async def test_three_attempts_on_repeated_failure():
    fetch = ScriptedFetch(ProviderError("down"))
    cache, _ = make(fetch)
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)
    assert fetch.calls == 3


@pytest.mark.anyio
async def test_success_on_third_attempt():
    fetch = ScriptedFetch(ProviderError("a"), ProviderError("b"), good())
    cache, _ = make(fetch)
    a = await cache.get(CELL, 7)
    assert fetch.calls == 3
    assert a.stale is False


@pytest.mark.anyio
async def test_retries_setting_respected():
    fetch = ScriptedFetch(ProviderError("down"))
    cache, _ = make(fetch, provider_retries=0)
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)
    assert fetch.calls == 1


@pytest.mark.anyio
async def test_backoff_between_attempts():
    fetch = ScriptedFetch(ProviderError("down"))
    cache, _ = make(fetch, provider_retry_backoff_seconds=0.05)
    start = time.monotonic()
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)
    assert time.monotonic() - start >= 0.1
    assert fetch.calls == 3


@pytest.mark.anyio
async def test_slow_provider_falls_back_at_deadline():
    late = good(T0 + timedelta(hours=4))
    slow = SlowFetch(2, late)
    cache, _ = await stale_cache(slow, refresh_deadline_seconds=0.3)
    start = time.monotonic()
    a = await cache.get(CELL, 7)
    assert time.monotonic() - start < 0.6
    assert a.stale is True
    assert a.fetched_at == T0
    await asyncio.sleep(0)
    assert cache._forecasts[CELL].fetched_at == T0


@pytest.mark.anyio
async def test_slow_provider_without_forecast_is_unavailable_at_deadline():
    cache, _ = make(SlowFetch(2, good()), refresh_deadline_seconds=0.3)
    start = time.monotonic()
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)
    assert time.monotonic() - start < 0.6


@pytest.mark.anyio
async def test_single_flight_one_call():
    fetch = SlowFetch(0.05, good())
    cache, _ = make(fetch)
    answers = await asyncio.gather(*(cache.get(CELL, 7) for _ in range(10)))
    assert fetch.calls == 1
    assert all(a == answers[0] for a in answers)
    assert answers[0].stale is False


@pytest.mark.anyio
async def test_single_flight_failure_shared():
    fetch = SlowFetch(0.05, ProviderError("down"))
    cache, _ = await stale_cache(fetch, provider_retries=0)
    answers = await asyncio.gather(*(cache.get(CELL, 7) for _ in range(5)))
    assert fetch.calls == 1
    assert all(a.stale is True and a.fetched_at == T0 for a in answers)


@pytest.mark.anyio
async def test_two_cells_two_calls():
    fetch = SlowFetch(0.05, good())
    cache, _ = make(fetch)
    await asyncio.gather(*(cache.get(c, 7) for c in [(1, 1), (2, 2)] * 5))
    assert fetch.calls == 2


@pytest.mark.anyio
async def test_waiters_bounded_by_deadline():
    slow = SlowFetch(2, good(T0 + timedelta(hours=4)))
    cache, _ = await stale_cache(slow, refresh_deadline_seconds=0.3)
    start = time.monotonic()
    answers = await asyncio.gather(*(cache.get(CELL, 7) for _ in range(5)))
    assert time.monotonic() - start < 0.6
    assert slow.calls == 1
    assert all(a.stale is True and a.fetched_at == T0 for a in answers)
    assert not cache._refreshing


@pytest.mark.anyio
async def test_pause_makes_no_calls():
    fetch = ScriptedFetch(ProviderError("down"))
    cache, clock = await stale_cache(fetch)
    a = await cache.get(CELL, 7)
    assert a.stale is True
    calls = fetch.calls
    for step in (1, 29, 29):  # +1 s, +30 s, +59 s
        clock.advance(step)
        a = await cache.get(CELL, 7)
        assert a.stale is True
        assert a.fetched_at == T0
    assert fetch.calls == calls


@pytest.mark.anyio
async def test_pause_retry_after_is_seconds_left():
    fetch = ScriptedFetch(ProviderError("down"))
    cache, clock = make(fetch)
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)
    calls = fetch.calls
    clock.advance(20)
    with pytest.raises(Unavailable) as exc:
        await cache.get(CELL, 7)
    assert exc.value.retry_after == 40
    assert fetch.calls == calls


@pytest.mark.anyio
async def test_pause_retry_after_rounds_up_and_is_at_least_1():
    fetch = ScriptedFetch(ProviderError("down"))
    cache, clock = make(fetch)
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)
    clock.advance(20.2)
    with pytest.raises(Unavailable) as exc:
        await cache.get(CELL, 7)
    assert exc.value.retry_after == 40
    clock.advance(39.7)
    with pytest.raises(Unavailable) as exc:
        await cache.get(CELL, 7)
    assert exc.value.retry_after == 1


@pytest.mark.anyio
async def test_after_pause_one_request_retries():
    failing = ScriptedFetch(ProviderError("down"))
    cache, clock = await stale_cache(failing)
    await cache.get(CELL, 7)
    clock.advance(61)
    fetch = SlowFetch(0.05, good(clock.now()))
    cache._fetch = fetch
    answers = await asyncio.gather(*(cache.get(CELL, 7) for _ in range(5)))
    assert fetch.calls == 1
    assert all(a.stale is False for a in answers)


@pytest.mark.anyio
async def test_success_clears_pause():
    fetch = ScriptedFetch(
        ProviderError("a"), ProviderError("b"), ProviderError("c"), good(T0 + timedelta(seconds=61))
    )
    cache, clock = make(fetch)
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)
    clock.advance(61)
    await cache.get(CELL, 7)
    assert fetch.calls == 4
    assert CELL not in cache._paused_until
    # Expired again later: a failure now is a new refresh, not blocked by an old pause.
    clock.advance(3 * 3600 + 1)
    cache._fetch = ScriptedFetch(good(clock.now()))
    a = await cache.get(CELL, 7)
    assert a.stale is False
    assert cache._fetch.calls == 1


@pytest.mark.anyio
async def test_fresh_beats_pause():
    fetch = ScriptedFetch(good())
    cache, clock = make(fetch)
    await cache.get(CELL, 7)
    cache._paused_until[CELL] = clock.now() + timedelta(seconds=60)
    a = await cache.get(CELL, 7)
    assert a.stale is False
    assert fetch.calls == 1


@pytest.mark.anyio
async def test_unavailable_answer_starts_no_pause():
    # Today missing (5.7) is not a provider failure.
    tomorrow = Forecast(days=good().days[1:], fetched_at=T0, timezone_name="Asia/Jerusalem")
    fetch = ScriptedFetch(tomorrow, good())
    cache, clock = make(fetch)
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)
    assert CELL not in cache._paused_until


@pytest.mark.anyio
async def test_failed_refresh_retry_after_is_pause_length():
    cache, _ = make(ScriptedFetch(ProviderError("down")), failure_pause_seconds=45)
    with pytest.raises(Unavailable) as exc:
        await cache.get(CELL, 7)
    assert exc.value.retry_after == 45


@pytest.mark.anyio
async def test_bug_does_not_start_pause():
    fetch = ScriptedFetch(KeyError("bug"))
    cache, _ = make(fetch)
    with pytest.raises(KeyError):
        await cache.get(CELL, 7)
    assert fetch.calls == 1
    assert CELL not in cache._paused_until
    assert not cache._refreshing
    with pytest.raises(KeyError):
        await cache.get(CELL, 7)
    assert fetch.calls == 2
