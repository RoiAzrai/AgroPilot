"""Open-Meteo response validation (design 5.5, FR-2.8).

Only this module knows Open-Meteo field names. Anything doubtful raises
ProviderError; we never return a number the provider did not give.
"""

import logging
import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from config import Settings

# Their DEBUG/INFO records contain the full URL, including the API key.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("provider")

SOURCE = "open-meteo"
FORECAST_DAYS = 8

_ET0 = "et0_fao_evapotranspiration"
_RAIN = "precipitation_sum"
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Day:
    date: date
    et0_mm: float
    rain_mm: float


@dataclass(frozen=True)
class Forecast:
    days: tuple[Day, ...]
    fetched_at: datetime
    timezone_name: str


class ProviderError(Exception):
    """The provider answer is unusable. The message is the reason only."""


def _timezone_name(payload: dict) -> str:
    name = payload.get("timezone")
    if not isinstance(name, str) or not name:
        raise ProviderError("timezone missing or not a string")
    try:
        ZoneInfo(name)
    except Exception:
        raise ProviderError("unknown timezone") from None
    return name


def _check_unit(units: object, key: str) -> None:
    if not isinstance(units, dict) or units.get(key) != "mm":
        raise ProviderError(f"unit of {key} is not mm")


def _array(daily: dict, key: str) -> list:
    arr = daily.get(key)
    if not isinstance(arr, list):
        raise ProviderError(f"daily.{key} missing or not a list")
    if len(arr) != FORECAST_DAYS:
        raise ProviderError(f"daily.{key} has {len(arr)} items, expected {FORECAST_DAYS}")
    return arr


def _number(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError(f"daily.{key} has a non-number value")
    try:
        number = float(value)
    except OverflowError:
        raise ProviderError(f"daily.{key} has a non-finite value") from None
    if not math.isfinite(number):
        raise ProviderError(f"daily.{key} has a non-finite value")
    if number < 0:
        raise ProviderError(f"daily.{key} has a negative value")
    return number


def _date(value: object) -> date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ProviderError("daily.time has a value that is not YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ProviderError("daily.time has an invalid date") from None


def parse_forecast(payload: object, fetched_at: datetime) -> Forecast:
    if not isinstance(payload, dict):
        raise ProviderError("response is not a JSON object")
    timezone_name = _timezone_name(payload)
    units = payload.get("daily_units")
    _check_unit(units, _ET0)
    _check_unit(units, _RAIN)
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise ProviderError("daily missing or not an object")
    times = _array(daily, "time")
    et0s = _array(daily, _ET0)
    rains = _array(daily, _RAIN)

    dates = [_date(t) for t in times]
    for prev, cur in zip(dates, dates[1:]):
        if cur - prev != timedelta(days=1):
            raise ProviderError("daily.time dates are not consecutive")

    days = tuple(
        Day(d, _number(e, _ET0), _number(r, _RAIN))
        for d, e, r in zip(dates, et0s, rains)
    )
    return Forecast(days=days, fetched_at=fetched_at, timezone_name=timezone_name)


def _fail(reason: str) -> ProviderError:
    logger.warning("provider attempt failed: %s", reason)
    return ProviderError(reason)


async def fetch_forecast(
    client: httpx.AsyncClient,
    settings: Settings,
    lat: float,
    lon: float,
    now: Callable[[], datetime],
) -> Forecast:
    """One provider attempt. Every failure becomes ProviderError."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": f"{_ET0},{_RAIN}",
        "forecast_days": FORECAST_DAYS,
        "timezone": "auto",
    }
    if settings.provider_api_key:
        params["apikey"] = settings.provider_api_key
    try:
        response = await client.get(
            settings.provider_base_url,
            params=params,
            timeout=settings.provider_attempt_timeout_seconds,
        )
    except httpx.TimeoutException:
        raise _fail("provider timed out") from None
    except httpx.TransportError as exc:
        raise _fail(f"provider connection failed ({type(exc).__name__})") from None
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        raise _fail(f"provider request failed ({type(exc).__name__})") from None
    fetched_at = now()
    if response.status_code != 200:
        raise _fail(f"provider returned status {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        raise _fail("provider body is not JSON") from None
    try:
        return parse_forecast(payload, fetched_at)
    except ProviderError as exc:
        logger.warning("provider attempt failed: %s", exc)
        raise
    except Exception:
        raise _fail("provider payload could not be parsed") from None
