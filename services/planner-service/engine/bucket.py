from dataclasses import dataclass


def taw(available_water_mm_per_m: float, zr: float) -> float:
    """Total available water, mm (FAO-56 Eq. 82)."""
    return available_water_mm_per_m * zr


def raw(p: float, taw_mm: float) -> float:
    """Readily available water, mm (FAO-56 Eq. 83)."""
    return p * taw_mm


def effective_rain(rain_mm: float, et0_mm: float) -> float:
    """I16: rain below 0.2 * ET0 is ignored."""
    return rain_mm if rain_mm >= 0.2 * et0_mm else 0.0


def bucket_mm(taw_mm: float, dr_end: float) -> float:
    """The level reported for the day."""
    return taw_mm - dr_end


@dataclass(frozen=True)
class StepResult:
    irrigation_mm: float
    dr_end: float
    refilling: bool


def step(
    dr_prev: float,
    rain_mm: float,
    et0_mm: float,
    etc_mm: float,
    taw_mm: float,
    raw_mm: float,
    cap_mm: float,
    refilling: bool,
) -> StepResult:
    """One day of the bucket (SKILL.md "The bucket"). Values are unrounded."""
    dr_start = max(dr_prev - effective_rain(rain_mm, et0_mm), 0.0)
    need = dr_start + etc_mm
    if refilling or need > raw_mm:
        irrigation = min(need, cap_mm)
        dr_end = min(need - irrigation, taw_mm)  # I17; `need` itself is not capped
        return StepResult(irrigation, dr_end, dr_end > 0)
    return StepResult(0.0, min(need, taw_mm), False)
