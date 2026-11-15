"""In-memory forecast cache (design 5.6 steps 1, 4, 5; 5.7).

One entry per cell. Time comes only from the injected clock (UTC, aware).
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
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

    async def get(self, cell: Cell, days: int) -> Answer:
        now = self._clock()
        forecast = self._forecasts.get(cell)
        if forecast and self._age(forecast, now) < self._settings.forecast_fresh_seconds:
            return self._answer(forecast, days, now, stale=False)
        return await self._refresh(cell, days)

    async def _refresh(self, cell: Cell, days: int) -> Answer:
        try:
            forecast = await self._fetch(cell)
        except ProviderError as exc:
            return self._fall_back(cell, days, str(exc))
        self._forecasts[cell] = forecast
        return self._answer(forecast, days, self._clock(), stale=False)

    def _fall_back(self, cell: Cell, days: int, reason: str) -> Answer:
        now = self._clock()
        forecast = self._forecasts.get(cell)
        if forecast and self._age(forecast, now) <= self._settings.forecast_max_stale_seconds:
            logger.warning("serving stale forecast for cell %s: %s", cell, reason)
            return self._answer(forecast, days, now, stale=True)
        logger.warning("no usable forecast for cell %s: %s", cell, reason)
        raise Unavailable(self._settings.retry_after_seconds)

    @staticmethod
    def _age(forecast: Forecast, now: datetime) -> float:
        return (now - forecast.fetched_at).total_seconds()

    def _answer(self, forecast: Forecast, days: int, now: datetime, stale: bool) -> Answer:
        today = now.astimezone(ZoneInfo(forecast.timezone_name)).date()
        remaining = [d for d in forecast.days if d.date >= today]
        if len(remaining) < days or not remaining or remaining[0].date != today:
            logger.warning("forecast does not cover local today and %d days", days)
            raise Unavailable(self._settings.retry_after_seconds)
        return Answer(days=remaining[:days], fetched_at=forecast.fetched_at, stale=stale)
