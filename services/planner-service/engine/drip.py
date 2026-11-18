import math
from decimal import ROUND_HALF_UP, Decimal

# Decimal places kept before the half-up step; removes float noise (~1e-13), I19.
ROUNDING_PLACES = 6


def _finite(name: str, value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return value


def _positive(name: str, value: float) -> float:
    _finite(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value!r}")
    return value


def round_half_up_places(x: float, places: int) -> float:
    """I19: round to ROUNDING_PLACES first, then half up to `places`."""
    _finite("x", x)
    exp = Decimal(1).scaleb(-places)
    d = Decimal(repr(round(x, ROUNDING_PLACES)))
    return float(d.quantize(exp, rounding=ROUND_HALF_UP))


def round_half_up(x: float) -> int:
    """I19/I20: whole number, half up (not Python's round())."""
    _finite("x", x)
    return int(Decimal(repr(round(x, ROUNDING_PLACES))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cap_mm(
    max_daily_run_minutes: int,
    flow_lph: float,
    row_spacing_m: float,
    emitter_spacing_m: float,
) -> float:
    """I23: the most water (mm) one day's run can deliver."""
    _positive("flow_lph", flow_lph)
    _positive("row_spacing_m", row_spacing_m)
    _positive("emitter_spacing_m", emitter_spacing_m)
    _finite("max_daily_run_minutes", max_daily_run_minutes)
    return max_daily_run_minutes * flow_lph / (row_spacing_m * emitter_spacing_m) / 60


def litres(irrigation_mm: float, area_m2: float) -> int:
    """I19: 1 mm over 1 m2 is 1 litre."""
    _finite("irrigation_mm", irrigation_mm)
    _finite("area_m2", area_m2)
    return round_half_up(irrigation_mm * area_m2)


def run_minutes(
    irrigation_mm: float,
    row_spacing_m: float,
    emitter_spacing_m: float,
    flow_lph: float,
) -> int:
    """I20: from the unrounded I; area cancels out."""
    _finite("irrigation_mm", irrigation_mm)
    _positive("row_spacing_m", row_spacing_m)
    _positive("emitter_spacing_m", emitter_spacing_m)
    _positive("flow_lph", flow_lph)
    return round_half_up(irrigation_mm * row_spacing_m * emitter_spacing_m / flow_lph * 60)
