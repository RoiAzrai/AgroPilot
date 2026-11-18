from datetime import date, timedelta
from pathlib import Path

import pytest

from engine.crops import UnknownCrop
from engine.plan import DayWeather, PlotInputs, build_plan

DAY1 = date(2031, 6, 1)  # a fake date: the engine must not care about the clock


def plan_for(
    *,
    crop_id="tomato",
    aw=83.0,
    season_day=80,
    et0=5.0,
    rain=None,
    area=1000.0,
    row=1.5,
    em=0.4,
    flow=1.6,
    bucket_start=1.0,
    cap_minutes=1440,
    override=None,
    days=7,
    stale=None,
):
    """Plan whose day 1 is `season_day` (<= 0 means before planting)."""
    rain = rain or {}
    stale = stale or {}
    plot = PlotInputs(
        crop_id=crop_id,
        planting_date=DAY1 - timedelta(days=season_day - 1),
        area_m2=area,
        row_spacing_m=row,
        emitter_spacing_m=em,
        flow_lph=flow,
        available_water_mm_per_m=aw,
    )
    weather = [
        DayWeather(
            date=DAY1 + timedelta(days=d),
            et0_mm=et0,
            rain_mm=rain.get(d + 1, 0.0),
            stale=stale.get(d + 1, False),
        )
        for d in range(days)
    ]
    return build_plan(plot, weather, bucket_start, cap_minutes, override)


def col(days, name):
    return [getattr(d, name) for d in days]


def approx(values, abs=1e-9):
    return pytest.approx(values, abs=abs)


# --- cases from the skill (cases.md) ---------------------------------------

def test_case1():
    days = plan_for()
    assert col(days, "bucket_mm") == approx([52.35, 46.60, 40.85, 35.10, 58.10, 52.35, 46.60])
    assert col(days, "run_minutes") == [0, 0, 0, 0, 647, 0, 0]
    assert days[4].litres == 28750
    assert col(days, "kc") == [1.15] * 7
    assert col(days, "bucket_capacity_mm") == approx([58.10] * 7)
    assert col(days, "stage") == ["mid"] * 7


def test_case2():
    days = plan_for(
        crop_id="bell-pepper", season_day=40, et0=4.0, area=400.0, row=1.2, em=0.3, flow=2.0
    )
    assert col(days, "kc") == [0.7286, 0.7414, 0.7543, 0.7671, 0.78, 0.7929, 0.8057]
    assert col(days, "bucket_capacity_mm") == approx(
        [31.54, 31.92, 32.31, 32.69, 33.07, 33.46, 33.84], abs=0.006
    )
    # cases.md shows 3 decimals; the served values have 2.
    assert col(days, "bucket_mm") == approx(
        [28.626, 26.043, 23.409, 32.689, 29.952, 27.164, 24.324], abs=0.006
    )
    assert days[3].bucket_mm == 32.69  # irrigation day: full
    assert days[3].litres == 4786
    assert days[3].run_minutes == 129
    assert [d.run_minutes for d in days if d is not days[3]] == [0] * 6
    assert col(days, "stage") == ["dev"] * 7


def test_case3_rain():
    days = plan_for(rain={2: 0.5, 4: 12.0})
    assert col(days, "bucket_mm") == approx([52.35, 46.60, 40.85, 47.10, 41.35, 35.60, 58.10])
    assert col(days, "run_minutes") == [0, 0, 0, 0, 0, 0, 636]
    assert days[6].litres == 28250
    assert days[1].rain_mm == 0.5  # ignored by the bucket, still reported


def test_case5_north_block_cap():
    days = plan_for(aw=175.0, et0=6.0, flow=1.0, bucket_start=0.7)
    assert col(days, "bucket_mm") == approx([78.85, 111.95, 122.50, 115.60, 108.70, 101.80, 94.90])
    assert col(days, "litres") == [0, 40000, 17450, 0, 0, 0, 0]
    assert col(days, "run_minutes") == [0, 1440, 628, 0, 0, 0, 0]


def test_rain_on_continuation_day():
    # Case 5 with 12 mm on day 3: need = 10.55 - 12 -> 0 + 6.9, so 6.9 mm.
    days = plan_for(aw=175.0, et0=6.0, flow=1.0, bucket_start=0.7, rain={3: 12.0})
    assert days[2].litres == 6900
    assert days[2].run_minutes == 248
    assert days[2].bucket_mm == 122.5
    assert days[3].bucket_mm == 115.6


def test_task_example_and_override_zero():
    # Lecturer example: 6.9 mm x 1000 m2 = 6900 L, 248 min. Override 0 = irrigate ETc daily (I21).
    days = plan_for(et0=6.0, flow=1.0, override=0)
    assert col(days, "litres") == [6900] * 7
    assert col(days, "run_minutes") == [248] * 7
    assert col(days, "bucket_mm") == col(days, "bucket_capacity_mm")


def test_override_half():
    # Case 1 with p = 0.5: RAW 29.05. Day 5: Dr_start 23.00 + 5.75 = 28.75 <= 29.05, no irrigation
    # (the default p 0.4 irrigates on day 5). Day 6: 28.75 + 5.75 = 34.50 > 29.05.
    # I = 34.50 mm -> 34500 L; minutes = 34.5 * 1.5 * 0.4 / 1.6 * 60 = 776.25 -> 776.
    days = plan_for(override=0.5)
    assert col(days, "run_minutes") == [0, 0, 0, 0, 0, 776, 0]
    assert days[5].litres == 34500
    assert days[4].bucket_mm == 29.35  # 58.10 - 28.75
    assert days[5].bucket_mm == 58.10


# --- stages ----------------------------------------------------------------

def test_not_planted_day():
    # Day 1 is season day 0, day 2 is season day 1 (ini, Kc 0.60, Zr 0.20).
    # Sand 83, bucket_start 0.9: TAW(day 2) = 83 * 0.20 = 16.60,
    # Dr_0 = (1 - 0.9) * 16.60 = 1.66, ETc = 0.60 * 5.0 = 3.00,
    # RAW = 0.4 * 16.60 = 6.64 > 1.66 + 3.00 = 4.66, so no irrigation,
    # Dr_end = 4.66, bucket_mm = 16.60 - 4.66 = 11.94.
    days = plan_for(season_day=0, bucket_start=0.9, days=3)
    d1, d2, _ = days
    assert d1.stage == "not_planted"
    assert (d1.litres, d1.run_minutes) == (0, 0)
    assert (d1.kc, d1.bucket_mm, d1.bucket_capacity_mm) == (None, None, None)
    assert (d1.et0_mm, d1.rain_mm) == (5.0, 0.0)
    assert d2.stage == "ini"
    assert d2.kc == 0.6
    assert d2.bucket_capacity_mm == 16.60
    assert d2.bucket_mm == 11.94
    assert d2.run_minutes == 0


def test_season_ends_during_continuation():
    # Tomato, season day 135 (last day, late, Kc_end 0.80), empty bucket, 60-minute cap.
    # cap_mm = 60 * 1.6 / (1.5 * 0.4) / 60 = 2.6667 mm: day 1 irrigates the cap and the
    # refill is unfinished, but day 2 is "ended" and never irrigates.
    days = plan_for(season_day=135, bucket_start=0.0, cap_minutes=60, rain={2: 3.0})
    assert days[0].stage == "late"
    assert days[0].run_minutes == 60
    assert days[0].litres == 2667
    assert days[0].kc == 0.8
    for d in days[1:]:
        assert d.stage == "ended"
        assert (d.litres, d.run_minutes) == (0, 0)
        assert (d.kc, d.bucket_mm, d.bucket_capacity_mm) == (None, None, None)
        assert d.et0_mm == 5.0
    assert days[1].rain_mm == 3.0


def test_planting_after_whole_plan():
    days = plan_for(season_day=-10, days=3)
    assert col(days, "stage") == ["not_planted"] * 3
    assert col(days, "bucket_mm") == [None] * 3


def test_every_day_after_season_end():
    # Tomato season is 135 days; day 1 is season day 136 (> 135), so every day is "ended" (P2):
    # no irrigation, no Kc, no bucket. et0, rain and stale are copied from the input.
    days = plan_for(
        season_day=136, et0=4.2, rain={2: 7.5}, stale={3: True}, bucket_start=0.5, days=4
    )
    assert col(days, "stage") == ["ended"] * 4
    assert col(days, "litres") == [0] * 4
    assert col(days, "run_minutes") == [0] * 4
    assert col(days, "kc") == [None] * 4
    assert col(days, "bucket_mm") == [None] * 4
    assert col(days, "bucket_capacity_mm") == [None] * 4
    assert col(days, "et0_mm") == [4.2] * 4
    assert col(days, "rain_mm") == [0.0, 7.5, 0.0, 0.0]
    assert col(days, "stale") == [False, False, True, False]


# --- served rounding ---------------------------------------------------------

def test_kc_and_mm_served_half_up():
    # Tomato season day 31: kc = 0.60 + 1/40 * 0.55 = 0.61375 -> 0.6138 (half up).
    days = plan_for(season_day=31, days=1)
    assert days[0].kc == 0.6138
    # Season day 1, ET0 0: nothing is used, bucket = TAW = 83.025 * 0.20 = 16.605 -> 16.61.
    days = plan_for(aw=83.025, season_day=1, et0=0.0, days=1)
    assert days[0].bucket_capacity_mm == 16.61
    assert days[0].bucket_mm == 16.61


def test_et0_rain_pass_through():
    plot = PlotInputs("tomato", DAY1 - timedelta(days=79), 1000.0, 1.5, 0.4, 1.6, 83.0)
    weather = [DayWeather(DAY1, 2.8600000001, 0.987654), DayWeather(DAY1 + timedelta(1), 4.123456, 0.0)]
    days = build_plan(plot, weather, 1.0, 1440, None)
    assert days[0].et0_mm == 2.8600000001
    assert days[0].rain_mm == 0.987654
    assert days[1].et0_mm == 4.123456


def test_stale_copied_per_day():
    days = plan_for(stale={2: True, 5: True})
    assert col(days, "stale") == [False, True, False, False, True, False, False]
    # also on days without a crop
    days = plan_for(season_day=0, days=2, stale={1: True})
    assert col(days, "stale") == [True, False]


def test_dates_come_from_weather():
    days = plan_for()
    assert col(days, "date") == [DAY1 + timedelta(days=d) for d in range(7)]


def test_unknown_crop():
    with pytest.raises(UnknownCrop):
        plan_for(crop_id="wheat")


def test_engine_has_no_clock():
    forbidden = ("now(", "today(", "import time", "httpx", "fastapi", "config")
    for path in Path("engine").glob("*.py"):
        text = path.read_text()
        for word in forbidden:
            assert word not in text, f"{path} contains {word!r}"
