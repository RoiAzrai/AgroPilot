"""The only module that talks HTTP. Every answer is parsed strictly; failures are typed.

No retries (P8). Each call is one request inside `asyncio.timeout` (P7): httpx timeouts
apply per phase, so a slow trickle could outlive them.
"""

import asyncio
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from config import Settings
from engine.crops import get_crop
from engine.plan import DayWeather

REGISTRY = "registry-service"
WEATHER = "weather-service"
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class UpstreamUnavailable(Exception):
    """Connection error, timeout or 5xx. `retry_after` is in seconds."""

    def __init__(self, service: str, retry_after: int) -> None:
        super().__init__(f"{service} is unavailable")
        self.service = service
        self.retry_after = retry_after


class PlotNotFound(Exception):
    pass


class UnexpectedUpstream(Exception):
    pass


@dataclass(frozen=True)
class PlotRecord:
    area_m2: float
    crop_id: str
    planting_date: date
    soil_id: str
    row_spacing_m: float
    emitter_spacing_m: float
    emitter_id: str
    lat: float
    lon: float


@dataclass(frozen=True)
class Forecast:
    days: list[DayWeather]
    past_days_returned: int
    fetched_at: str
    stale: bool


def _unexpected(service: str, what: str) -> UnexpectedUpstream:
    return UnexpectedUpstream(f"{service}: {what}")


def _number(service: str, body: dict[str, Any], key: str) -> float:
    value = body.get(key)
    # bool is an int in Python, and still not a number here.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _unexpected(service, f"{key} is not a finite number")
    return float(value)


def _positive(service: str, body: dict[str, Any], key: str) -> float:
    value = _number(service, body, key)
    if value <= 0:
        raise _unexpected(service, f"{key} must be above 0")
    return value


def _text(service: str, body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise _unexpected(service, f"{key} is not a text")
    return value


def _iso_date(service: str, value: Any, key: str) -> date:
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value):
        raise _unexpected(service, f"{key} is not an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _unexpected(service, f"{key} is not a real date") from None


def _int_in(service: str, body: dict[str, Any], key: str, low: int, high: int) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _unexpected(service, f"{key} must be an integer from {low} to {high}")
    return value


class Upstream:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def _get(
        self, service: str, base: str, path: str, timeout: float, params: dict | None = None
    ) -> httpx.Response:
        """One request, bounded as a whole. Returns a 200 response; everything else raises
        (a registry 404 is returned as is, for the caller to read)."""
        try:
            async with asyncio.timeout(timeout):
                response = await self._client.get(base.rstrip("/") + path, params=params)
        except (TimeoutError, httpx.TransportError):
            raise UpstreamUnavailable(service, self._settings.retry_after_seconds) from None
        if response.status_code >= 500:
            raise UpstreamUnavailable(service, self._retry_after(service, response))
        return response

    def _retry_after(self, service: str, response: httpx.Response) -> int:
        default = self._settings.retry_after_seconds
        if service != WEATHER:
            return default
        value = response.headers.get("Retry-After", "")
        return int(value) if value.isdecimal() and int(value) > 0 else default

    async def _registry_json(self, path: str) -> dict[str, Any]:
        response = await self._get(
            REGISTRY, self._settings.registry_url, path, self._settings.registry_timeout_seconds
        )
        return self._json_object(REGISTRY, response)

    @staticmethod
    def _json_object(service: str, response: httpx.Response) -> dict[str, Any]:
        if response.status_code != 200:
            raise _unexpected(service, f"unexpected status {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            raise _unexpected(service, "the answer is not JSON") from None
        if not isinstance(body, dict):
            raise _unexpected(service, "the answer is not a JSON object")
        return body

    async def get_plot(self, plot_id: str) -> PlotRecord:
        response = await self._get(
            REGISTRY,
            self._settings.registry_url,
            f"/v1/plots/{quote(plot_id, safe='')}",
            self._settings.registry_timeout_seconds,
        )
        if response.status_code == 404:
            raise PlotNotFound(plot_id)
        body = self._json_object(REGISTRY, response)
        return PlotRecord(
            area_m2=_positive(REGISTRY, body, "area_m2"),
            crop_id=_text(REGISTRY, body, "crop_id"),
            planting_date=_iso_date(REGISTRY, body.get("planting_date"), "planting_date"),
            soil_id=_text(REGISTRY, body, "soil_id"),
            row_spacing_m=_positive(REGISTRY, body, "row_spacing_m"),
            emitter_spacing_m=_positive(REGISTRY, body, "emitter_spacing_m"),
            emitter_id=_text(REGISTRY, body, "emitter_id"),
            lat=_number(REGISTRY, body, "lat"),
            lon=_number(REGISTRY, body, "lon"),
        )

    async def get_soil_water(self, soil_id: str) -> float:
        body = await self._registry_json(f"/v1/soils/{quote(soil_id, safe='')}")
        return _positive(REGISTRY, body, "available_water_mm_per_m")

    async def get_flow_lph(self, emitter_id: str) -> float:
        body = await self._registry_json(f"/v1/emitters/{quote(emitter_id, safe='')}")
        return _positive(REGISTRY, body, "flow_lph")

    async def check_crop(self, crop_id: str) -> None:
        """The registry knows the crop (else unexpected), and the engine has its
        coefficients (else `UnknownCrop`, P9: a data problem, not a request problem)."""
        await self._registry_json(f"/v1/crops/{quote(crop_id, safe='')}")
        get_crop(crop_id)

    async def get_forecast(self, lat: float, lon: float, days: int, past_days: int = 0) -> Forecast:
        params: dict[str, Any] = {"lat": lat, "lon": lon, "days": days}
        if past_days:
            params["past_days"] = past_days
        response = await self._get(
            WEATHER,
            self._settings.weather_url,
            "/v1/forecast",
            self._settings.weather_timeout_seconds,
            params,
        )
        body = self._json_object(WEATHER, response)

        stale = body.get("stale")
        if not isinstance(stale, bool):
            raise _unexpected(WEATHER, "stale is not a boolean")
        fetched_at = _text(WEATHER, body, "fetched_at")
        # The field exists only when past days were asked for.
        past_returned = _int_in(WEATHER, body, "past_days_returned", 0, past_days) if past_days else 0
        if not past_days and "past_days_returned" in body:
            raise _unexpected(WEATHER, "past_days_returned without past_days")

        raw_days = body.get("days")
        if not isinstance(raw_days, list) or len(raw_days) != days + past_returned:
            raise _unexpected(WEATHER, "wrong number of days")
        weather: list[DayWeather] = []
        for raw in raw_days:
            if not isinstance(raw, dict):
                raise _unexpected(WEATHER, "a day is not an object")
            et0, rain = (_number(WEATHER, raw, k) for k in ("et0_mm", "rain_mm"))
            if et0 < 0 or rain < 0:
                raise _unexpected(WEATHER, "et0_mm and rain_mm must not be negative")
            day = _iso_date(WEATHER, raw.get("date"), "date")
            if weather and day != weather[-1].date + timedelta(days=1):
                raise _unexpected(WEATHER, "dates are not consecutive")
            weather.append(DayWeather(day, et0, rain, stale))
        return Forecast(weather, past_returned, fetched_at, stale)
