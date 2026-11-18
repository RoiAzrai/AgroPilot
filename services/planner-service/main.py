import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Annotated

import httpx
from fastapi import FastAPI, Query, Request

from config import Settings, get_settings
from engine.plan import PlotInputs, build_plan
from errors import register_error_handlers
from models import PlanOut
from upstream import Upstream

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
