from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from engine.bucket import bucket_mm as bucket_level
from engine.bucket import raw, step, taw
from engine.crops import get_crop
from engine.drip import cap_mm, litres, round_half_up_places, run_minutes
from engine.season import kc as crop_kc
from engine.season import root_depth, season_day, stage


@dataclass(frozen=True)
class PlotInputs:
    crop_id: str
    planting_date: date
    area_m2: float
    row_spacing_m: float
    emitter_spacing_m: float
    flow_lph: float
    available_water_mm_per_m: float


@dataclass(frozen=True)
class DayWeather:
    date: date
    et0_mm: float
    rain_mm: float
    stale: bool = False


@dataclass(frozen=True)
class PlanDay:
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


def build_plan(
    plot: PlotInputs,
    weather: Sequence[DayWeather],
    bucket_start: float,
    max_daily_run_minutes: int,
    depletion_fraction_override: float | None,
) -> list[PlanDay]:
    """The per-day plan. Pure: dates come from `weather`, nothing else is read."""
    crop = get_crop(plot.crop_id)
    p = crop.p if depletion_fraction_override is None else depletion_fraction_override
    cap = cap_mm(max_daily_run_minutes, plot.flow_lph, plot.row_spacing_m, plot.emitter_spacing_m)

    days: list[PlanDay] = []
    dr: float | None = None  # set on the first planted day from bucket_start
    refilling = False
    for w in weather:
        i = season_day(w.date, plot.planting_date)
        st = stage(crop, i)
        if st in ("not_planted", "ended"):
            # Checked before kc()/root_depth(), which raise on these days (P2, Q4).
            days.append(PlanDay(w.date, st, w.et0_mm, w.rain_mm, None, 0, 0, None, None, w.stale))
            continue

        taw_mm = taw(plot.available_water_mm_per_m, root_depth(crop, i))
        if dr is None:
            dr = (1 - bucket_start) * taw_mm
        kc_i = crop_kc(crop, i)
        r = step(dr, w.rain_mm, w.et0_mm, kc_i * w.et0_mm, taw_mm, raw(p, taw_mm), cap, refilling)
        dr, refilling = r.dr_end, r.refilling

        days.append(
            PlanDay(
                date=w.date,
                stage=st,
                et0_mm=w.et0_mm,
                rain_mm=w.rain_mm,
                kc=round_half_up_places(kc_i, 4),
                litres=litres(r.irrigation_mm, plot.area_m2),
                run_minutes=run_minutes(
                    r.irrigation_mm, plot.row_spacing_m, plot.emitter_spacing_m, plot.flow_lph
                ),
                bucket_mm=round_half_up_places(bucket_level(taw_mm, r.dr_end), 2),
                bucket_capacity_mm=round_half_up_places(taw_mm, 2),
                stale=w.stale,
            )
        )
    return days
