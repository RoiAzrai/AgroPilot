"""Response models (design 5.3). Request validation lives on the endpoint's query
parameters in main.py. Every number here is already rounded by the engine."""

from datetime import date

from pydantic import BaseModel


class DayOut(BaseModel):
    date: date
    stage: str
    et0_mm: float
    rain_mm: float
    kc: float | None
    litres: int
    run_minutes: int
    bucket_mm: float | None
    bucket_capacity_mm: float | None
    stale: bool


class PlanOut(BaseModel):
    plot_id: str
    crop: str
    bucket_start: float
    fetched_at: str
    stale: bool
    days: list[DayOut]
