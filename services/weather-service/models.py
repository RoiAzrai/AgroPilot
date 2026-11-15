"""Response models (design 5.3). Request validation lives on the endpoint's
query parameters in main.py."""

from datetime import date, datetime, timezone

from pydantic import BaseModel, field_serializer


class DayOut(BaseModel):
    date: date
    et0_mm: float
    rain_mm: float


class ForecastOut(BaseModel):
    lat: float
    lon: float
    source: str
    fetched_at: datetime
    stale: bool
    days: list[DayOut]

    @field_serializer("fetched_at")
    def _utc_seconds_z(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
