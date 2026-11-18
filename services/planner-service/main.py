import asyncio
import logging
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import FastAPI, Query, Request

from config import Settings, get_settings
from engine.crops import get_crop
from engine.plan import PlotInputs, build_plan
from engine.season import season_day, stage
from engine.suggestion import (
    MAX_PAST_DAYS,
    InvalidLastIrrigation,
    check_last_irrigation,
    past_days_requested,
    suggest,
)
from errors import AppError, register_error_handlers
from models import PlanOut, SuggestionOut
from upstream import Upstream

ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
SERVICE_LOGGERS = ("upstream", "errors", "main")
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


def utc_now() -> datetime:
    """The only clock in the service: used for the UTC+14 future check, nothing else."""
    return datetime.now(UTC)


def make_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()  # fails fast on invalid settings
    # make_client is looked up at call time, so tests can replace it.
    async with make_client(settings) as client:
        app.state.settings = settings
        app.state.upstream = Upstream(client, settings)
        yield


app = FastAPI(title="AgroPilot planner-service", version="0.1.0", lifespan=lifespan)
register_error_handlers(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/plots/{plot_id}/plan", response_model=PlanOut)
async def plan(
    request: Request,
    plot_id: str,
    days: Annotated[int, Query(ge=1, le=7)] = 7,
    bucket_start: Annotated[float, Query(ge=0, le=1, allow_inf_nan=False)] = 1.0,
) -> PlanOut:
    settings: Settings = request.app.state.settings
    upstream: Upstream = request.app.state.upstream

    plot = await upstream.get_plot(plot_id)  # its ids and lat/lon are needed first
    tasks = [
        asyncio.ensure_future(call)
        for call in (
            upstream.get_soil_water(plot.soil_id),
            upstream.get_flow_lph(plot.emitter_id),
            upstream.check_crop(plot.crop_id),
            upstream.get_forecast(plot.lat, plot.lon, days),
        )
    ]
    try:
        soil_water, flow_lph, _, forecast = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:  # the first failure decides; nothing else keeps running
            task.cancel()
        raise

    inputs = PlotInputs(
        crop_id=plot.crop_id,
        planting_date=plot.planting_date,
        area_m2=plot.area_m2,
        row_spacing_m=plot.row_spacing_m,
        emitter_spacing_m=plot.emitter_spacing_m,
        flow_lph=flow_lph,
        available_water_mm_per_m=soil_water,
    )
    plan_days = build_plan(
        inputs,
        forecast.days,
        bucket_start,
        settings.max_daily_run_minutes,
        settings.depletion_fraction_override,
    )
    return PlanOut(
        plot_id=plot_id,
        crop=plot.crop_id,
        bucket_start=bucket_start,
        fetched_at=forecast.fetched_at,
        stale=forecast.stale,
        days=[asdict(day) for day in plan_days],
    )


def _parse_last_irrigation(value: str) -> date:
    """Step 1 of the fixed order (design 5.4): runs before any upstream call."""
    try:
        if not ISO_DATE.fullmatch(value):
            raise ValueError
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AppError(422, "VALIDATION", "last_irrigation must be a date, YYYY-MM-DD") from None
    # The latest date that has started anywhere on Earth, as the registry checks.
    if parsed > (utc_now() + timedelta(hours=14)).date():
        raise AppError(422, "VALIDATION", "last_irrigation cannot be in the future")
    return parsed


@app.get("/v1/plots/{plot_id}/bucket-suggestion", response_model=SuggestionOut)
async def bucket_suggestion(
    request: Request,
    plot_id: str,
    last_irrigation: Annotated[str, Query()],
) -> SuggestionOut:
    upstream: Upstream = request.app.state.upstream

    irrigated_on = _parse_last_irrigation(last_irrigation)  # 1
    plot = await upstream.get_plot(plot_id)  # 2
    # One weather call: today is the date after the past days (design Q1).
    # The emitter is not fetched: the suggestion never uses flow_lph.
    tasks = [
        asyncio.ensure_future(call)
        for call in (
            upstream.get_soil_water(plot.soil_id),
            upstream.check_crop(plot.crop_id),
            upstream.get_forecast(plot.lat, plot.lon, 1, MAX_PAST_DAYS),
        )
    ]
    try:
        soil_water, _, forecast = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:  # the first failure decides; nothing else keeps running
            task.cancel()
        raise

    today = forecast.days[forecast.past_days_returned].date
    needed = past_days_requested(irrigated_on, today)

    def answer(value: float | None, exact: bool, reason: str | None, requested: int, returned: int):
        return SuggestionOut(
            plot_id=plot_id,
            last_irrigation=irrigated_on,
            suggestion=value,
            exact=exact,
            reason=reason,
            past_days_requested=requested,
            past_days_returned=returned,
            stale=forecast.stale,
        )

    crop = get_crop(plot.crop_id)
    if stage(crop, season_day(today, plot.planting_date)) == "ended":  # 3: wins over 4
        return answer(None, False, "season_ended", 0, 0)
    try:
        check_last_irrigation(irrigated_on, today, plot.planting_date)  # 4
    except InvalidLastIrrigation as exc:
        raise AppError(422, "VALIDATION", str(exc)) from None

    past = forecast.days[: forecast.past_days_returned]
    result = suggest(  # 5: the last `needed` returned past days
        plot.crop_id,
        plot.planting_date,
        soil_water,
        irrigated_on,
        today,
        past[len(past) - needed :] if needed < len(past) else past,
    )
    return answer(result.value, result.exact, result.reason, result.past_days_requested, result.past_days_returned)
