"""In-memory forecast cache (design 5.6; 5.7).

One entry per cell. Freshness, stale age and the pause use the injected clock
(UTC, aware); the refresh deadline and the backoff are real time.
"""

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from cells import Cell
from config import Settings
from provider import Day, Forecast, ProviderError

logger = logging.getLogger("forecasts")

Clock = Callable[[], datetime]
Fetch = Callable[[Cell], Awaitable[Forecast]]


@dataclass(frozen=True)
class Answer:
    days: list[Day]
    fetched_at: datetime
    stale: bool
    past_days_returned: int = 0  # how many of `days` are before local today (W27)


class Unavailable(Exception):
    def __init__(self, retry_after: int):
        super().__init__("forecast unavailable")
        self.retry_after = retry_after


class ForecastCache:
    def __init__(self, fetch: Fetch, settings: Settings, clock: Clock):
        self._fetch = fetch
        self._settings = settings
        self._clock = clock
        self._forecasts: dict[Cell, Forecast] = {}
        self._refreshing: dict[Cell, asyncio.Future] = {}
        self._paused_until: dict[Cell, datetime] = {}
        self._tasks: set[asyncio.Task] = set()

    async def get(self, cell: Cell, days: int, past_days: int = 0) -> Answer:
        now = self._clock()
        forecast = self._forecasts.get(cell)
        if forecast and self._age(forecast, now) < self._settings.forecast_fresh_seconds:
            return self._answer(cell, forecast, days, past_days, now, stale=False)
        if self._paused(cell, now):
            return self._fall_back(cell, days, past_days, "paused after a failed refresh")
        future = self._refreshing.get(cell)
        if future is None:
            # Leader: the refresh task is bounded by the deadline itself.
            future = asyncio.get_running_loop().create_future()
            self._refreshing[cell] = future
            task = asyncio.create_task(self._refresh(cell, future))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            failure = await asyncio.shield(future)
        else:
            try:
                failure = await asyncio.wait_for(
                    asyncio.shield(future), self._settings.refresh_deadline_seconds
                )
            except TimeoutError:
                failure = "waited for the refresh past the deadline"
        if isinstance(failure, BaseException):
            raise failure
        if failure is not None:
            return self._fall_back(cell, days, past_days, failure)
        return self._answer(
            cell, self._forecasts[cell], days, past_days, self._clock(), stale=False
        )

    async def _refresh(self, cell: Cell, future: asyncio.Future) -> None:
        """Resolves `future` with None (success), a reason to fall back, or an
        unexpected exception (a bug: re-raised by every request, no pause).
        Only a provider failure or the deadline starts the pause."""
        outcome: str | BaseException | None = "refresh cancelled"
        pause = False
        try:
            async with asyncio.timeout(self._settings.refresh_deadline_seconds):
                forecast = await self._attempts(cell)
            self._forecasts[cell] = forecast
            self._paused_until.pop(cell, None)
            self._evict(self._clock())
            outcome = None
        except TimeoutError:
            outcome, pause = "refresh deadline exceeded", True
        except ProviderError as exc:
            outcome, pause = str(exc), True
        except Exception as exc:
            outcome = exc
        finally:
            if pause:
                until = self._clock() + timedelta(seconds=self._settings.failure_pause_seconds)
                self._paused_until[cell] = until
            del self._refreshing[cell]
            future.set_result(outcome)

    async def _attempts(self, cell: Cell) -> Forecast:
        attempts = 1 + self._settings.provider_retries
        for attempt in range(1, attempts + 1):
            if attempt > 1:
                await asyncio.sleep(self._settings.provider_retry_backoff_seconds)
            try:
                return await self._fetch(cell)
            except ProviderError as exc:
                logger.warning("attempt %d/%d failed for cell %s: %s", attempt, attempts, cell, exc)
                if not exc.retryable:
                    raise
                last = exc
        raise last

    def _evict(self, now: datetime) -> None:
        """Sweep on store, O(entries): drop forecasts past max-stale (never served
        again) and pauses that have expired. `_refreshing` is not touched, so a
        waiter of a running refresh still gets its entry."""
        max_stale = self._settings.forecast_max_stale_seconds
        for cell in [c for c, f in self._forecasts.items() if self._age(f, now) > max_stale]:
            del self._forecasts[cell]
        for cell in [c for c, until in self._paused_until.items() if now >= until]:
            del self._paused_until[cell]

    def _paused(self, cell: Cell, now: datetime) -> bool:
        paused_until = self._paused_until.get(cell)
        return paused_until is not None and now < paused_until

    def _retry_after(self, cell: Cell, now: datetime) -> int:
        """Seconds left in the pause (rounded up, at least 1), else RETRY_AFTER_SECONDS."""
        if not self._paused(cell, now):
            return self._settings.retry_after_seconds
        left = (self._paused_until[cell] - now).total_seconds()
        return max(math.ceil(left), 1)

    def _fall_back(self, cell: Cell, days: int, past_days: int, reason: str) -> Answer:
        now = self._clock()
        retry_after = self._retry_after(cell, now)
        forecast = self._forecasts.get(cell)
        if forecast and self._age(forecast, now) <= self._settings.forecast_max_stale_seconds:
            try:
                answer = self._answer(
                    cell, forecast, days, past_days, now, stale=True, retry_after=retry_after
                )
            except Unavailable:
                logger.warning("no usable forecast for cell %s: %s", cell, reason)
                raise
            logger.warning("serving stale forecast for cell %s: %s", cell, reason)
            return answer
        logger.warning("no usable forecast for cell %s: %s", cell, reason)
        raise Unavailable(retry_after)

    @staticmethod
    def _age(forecast: Forecast, now: datetime) -> float:
        return (now - forecast.fetched_at).total_seconds()

    def _answer(
        self,
        cell: Cell,
        forecast: Forecast,
        days: int,
        past_days: int,
        now: datetime,
        stale: bool,
        retry_after: int | None = None,
    ) -> Answer:
        """Up to `past_days` days before local today that the entry holds (W27: it
        may hold fewer), then local today .. today + days - 1. Every date present
        and in order, or Unavailable. Never pads or shifts a day."""
        today = now.astimezone(ZoneInfo(forecast.timezone_name)).date()
        window = [d for d in forecast.days if d.date >= today - timedelta(days=past_days)]
        returned = sum(1 for d in window if d.date < today)
        window = window[: returned + days]
        first = today - timedelta(days=returned)
        expected = [first + timedelta(days=i) for i in range(returned + days)]
        if returned < past_days:
            # Not a failure (W27): the provider logged the limit once per entry.
            logger.debug("cell %s: %d of %d past days available", cell, returned, past_days)
        if [d.date for d in window] != expected:
            logger.warning(
                "forecast does not cover %d past days, local today and %d days", returned, days
            )
            if retry_after is None:
                retry_after = self._settings.retry_after_seconds
            raise Unavailable(retry_after)
        return Answer(
            days=window, fetched_at=forecast.fetched_at, stale=stale, past_days_returned=returned
        )
