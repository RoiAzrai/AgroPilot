from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from engine.bucket import effective_rain, taw
from engine.crops import get_crop
from engine.drip import round_half_up_places
from engine.plan import DayWeather
from engine.season import kc as crop_kc
from engine.season import root_depth, season_day, stage

# The most past weather the weather-service serves (I15).
MAX_PAST_DAYS = 92


class InvalidLastIrrigation(ValueError):
    pass


@dataclass(frozen=True)
class Suggestion:
    value: float | None
    exact: bool
    reason: str | None
    past_days_requested: int
    past_days_returned: int


def past_days_requested(last_irrigation: date, today: date) -> int:
    """I22: the days D+1 .. yesterday. None when D is today or yesterday."""
    return max((today - last_irrigation).days - 1, 0)


def check_last_irrigation(last_irrigation: date, today: date, planting_date: date) -> None:
    """I15. Raises InvalidLastIrrigation for a date the planner can't simulate."""
    if last_irrigation > today:
        raise InvalidLastIrrigation("last_irrigation is in the future")
    if last_irrigation < planting_date:
        raise InvalidLastIrrigation("last_irrigation is before the planting date")
    if (today - last_irrigation) > timedelta(days=MAX_PAST_DAYS):
        raise InvalidLastIrrigation(f"last_irrigation is more than {MAX_PAST_DAYS} days ago")


def suggest(
    crop_id: str,
    planting_date: date,
    available_water_mm_per_m: float,
    last_irrigation: date,
    today: date,
    past_weather: Sequence[DayWeather],
) -> Suggestion:
    """The bucket suggestion (SKILL.md). Pure: `today` and the past days are handed in.

    `past_weather` is what weather returned for D+1 .. yesterday, ascending.
    """
    crop = get_crop(crop_id)
    requested = past_days_requested(last_irrigation, today)
    returned = len(past_weather)

    today_i = season_day(today, planting_date)
    if stage(crop, today_i) == "ended":  # I18
        return Suggestion(None, False, "season_ended", requested, returned)
    if requested == 0:  # I22: D is today or yesterday
        return Suggestion(1.0, True, None, 0, 0)
    if returned == 0:
        return Suggestion(None, False, "insufficient_past_weather", requested, 0)

    # No irrigation. With fewer days than requested the bucket is assumed full at the
    # start of the first returned day (the optimistic bound, I22).
    dr = 0.0
    reached_empty = False
    for w in past_weather:
        i = season_day(w.date, planting_date)
        taw_i = taw(available_water_mm_per_m, root_depth(crop, i))
        etc = crop_kc(crop, i) * w.et0_mm
        dr = min(max(dr - effective_rain(w.rain_mm, w.et0_mm), 0.0) + etc, taw_i)  # I16, I17
        reached_empty = reached_empty or dr >= taw_i

    if returned < requested and not reached_empty:
        return Suggestion(None, False, "insufficient_past_weather", requested, returned)

    taw_today = taw(available_water_mm_per_m, root_depth(crop, today_i))  # I14
    fraction = min(max(1 - dr / taw_today, 0.0), 1.0)
    return Suggestion(round_half_up_places(fraction, 4), True, None, requested, returned)
