import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import FastAPI, Query, Request

from cells import cell_center, cell_of
from config import Settings, get_settings
from errors import register_error_handlers
from forecasts import ForecastCache
from models import DayOut, ForecastOut
from provider import PAST_DAYS, SOURCE, fetch_forecast

SERVICE_LOGGERS = ("provider", "forecasts", "main")
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _StderrHandler(logging.StreamHandler):
    """Writes to the current sys.stderr, looked up on every record."""

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, value) -> None:
        pass


def configure_logging() -> None:
    """The service's own loggers at INFO to stderr. uvicorn's loggers are not touched."""
    for name in SERVICE_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = _StderrHandler()
            handler.setFormatter(logging.Formatter(LOG_FORMAT))
            logger.addHandler(handler)


configure_logging()


def make_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # make_client and utc_now are looked up at call time, so tests can replace them.
    async with make_client(settings) as client:
        app.state.cache = ForecastCache(
            fetch=lambda cell: fetch_forecast(
                client, settings, *cell_center(cell), lambda: utc_now()
            ),
            settings=settings,
            clock=lambda: utc_now(),
        )
        yield


app = FastAPI(title="AgroPilot weather-service", version="0.1.0", lifespan=lifespan)
register_error_handlers(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/forecast", response_model=ForecastOut, response_model_exclude_none=True)
async def forecast(
    request: Request,
    lat: Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False)],
    lon: Annotated[float, Query(ge=-180, le=180, allow_inf_nan=False)],
    days: Annotated[int, Query(ge=1, le=7)] = 7,
    past_days: Annotated[int, Query(ge=0, le=PAST_DAYS)] = 0,
) -> ForecastOut:
    answer = await request.app.state.cache.get(cell_of(lat, lon), days, past_days=past_days)
    return ForecastOut(
        lat=lat,
        lon=lon,
        source=SOURCE,
        fetched_at=answer.fetched_at,
        stale=answer.stale,
        days=[DayOut(date=d.date, et0_mm=d.et0_mm, rain_mm=d.rain_mm) for d in answer.days],
        past_days_returned=answer.past_days_returned if past_days else None,
    )
