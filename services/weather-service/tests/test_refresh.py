import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from config import Settings
from forecasts import ForecastCache, Unavailable
from provider import Day, Forecast, ProviderError, fetch_forecast
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


# W1: only a timeout, a connection error or a status >= 500 is retried.


def real_fetch(handler, **kw):
    """The real provider code over a MockTransport; returns (fetch, calls)."""
    calls = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cfg = settings(**kw)

    async def fetch(cell):
        calls.append(cell)
        return await fetch_forecast(client, cfg, 31.25, 34.85, lambda: T0)

    return fetch, calls


@pytest.mark.anyio
@pytest.mark.parametrize("status", [400, 401, 403, 429])
async def test_client_error_is_not_retried_and_503_without_stale(status):
    fetch, calls = real_fetch(lambda r: httpx.Response(status))
    cache, _ = make(fetch)
    with pytest.raises(Unavailable) as info:
        await cache.get(CELL, 7)
    assert len(calls) == 1
    assert info.value.retry_after == 60  # same path as exhausted retries: the pause


@pytest.mark.anyio
@pytest.mark.parametrize("status", [400, 401, 403, 429])
async def test_client_error_is_not_retried_and_serves_stale(status):
    fetch, calls = real_fetch(lambda r: httpx.Response(status))
    cache, _ = await stale_cache(fetch)
    answer = await cache.get(CELL, 7)
    assert len(calls) == 1
    assert answer.stale is True


@pytest.mark.anyio
async def test_client_error_pauses_the_cell():
    fetch, calls = real_fetch(lambda r: httpx.Response(429))
    cache, _ = make(fetch)
    for _ in range(2):
        with pytest.raises(Unavailable):
            await cache.get(CELL, 7)
    assert len(calls) == 1


@pytest.mark.anyio
async def test_server_error_is_still_retried():
    fetch, calls = real_fetch(lambda r: httpx.Response(500))
    cache, _ = make(fetch)
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)
    assert len(calls) == 3


@pytest.mark.anyio
async def test_timeout_is_still_retried():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    fetch, calls = real_fetch(handler)
    cache, _ = make(fetch)
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)
    assert len(calls) == 3


@pytest.mark.anyio
async def test_key_not_logged_on_client_error(caplog):
    caplog.set_level(logging.DEBUG)
    fetch, calls = real_fetch(lambda r: httpx.Response(401), provider_api_key="secret-key-123")
    cache, _ = make(fetch)
    with pytest.raises(Unavailable):
        await cache.get(CELL, 7)
    assert len(calls) == 1
    assert "secret-key-123" not in caplog.text


# W2: storing a forecast sweeps what can never be served again.

H = 3600


@pytest.mark.anyio
async def test_store_evicts_forecasts_past_max_stale_and_expired_pauses():
    old, kept, new, paused_old, paused_live = (1, 1), (2, 2), (3, 3), (4, 4), (5, 5)
    cache, clock = make(ScriptedFetch(good(T0)))
    await cache.get(old, 7)
    clock.advance(5 * H)
    cache._fetch = ScriptedFetch(good(clock.now()))
    await cache.get(kept, 7)
    cache._fetch = ScriptedFetch(ProviderError("down"))
    with pytest.raises(Unavailable):
        await cache.get(paused_old, 7)  # paused for 60 s from T0 + 5 h
    clock.advance(20 * H)  # `old` is 25 h old, `kept` 20 h
    cache._fetch = ScriptedFetch(ProviderError("down"))
    with pytest.raises(Unavailable):
        await cache.get(paused_live, 7)  # paused for 60 s from now
    assert set(cache._forecasts) == {old, kept}
    assert set(cache._paused_until) == {paused_old, paused_live}

    cache._fetch = ScriptedFetch(good(clock.now()))
    await cache.get(new, 7)

    assert set(cache._forecasts) == {kept, new}
    assert set(cache._paused_until) == {paused_live}


@pytest.mark.anyio
async def test_entry_exactly_max_stale_old_stays():
    cache, clock = make(ScriptedFetch(good(T0)))
    await cache.get(CELL, 7)
    clock.advance(24 * H)
    cache._fetch = ScriptedFetch(good(clock.now()))
    await cache.get((9, 9), 7)
    assert CELL in cache._forecasts  # still servable as stale (<=)


@pytest.mark.anyio
async def test_sweep_does_not_break_a_running_refresh_and_its_waiter():
    slow_cell = (7, 7)
    cache, clock = make(ScriptedFetch(good(T0)), refresh_deadline_seconds=2)
    await cache.get(slow_cell, 7)
    clock.advance(25 * H)  # the old entry of slow_cell is past max-stale

    async def fetch(cell):
        if cell == slow_cell:
            await asyncio.sleep(0.1)
        return good(clock.now())

    cache._fetch = fetch
    leader, waiter, other = await asyncio.gather(
        cache.get(slow_cell, 7), cache.get(slow_cell, 7), cache.get((8, 8), 7)
    )
    assert leader.stale is False and waiter.stale is False and other.stale is False
    assert set(cache._forecasts) == {slow_cell, (8, 8)}
