from datetime import date, timedelta

import pytest

from engine.plan import DayWeather
from engine.suggestion import (
    MAX_PAST_DAYS,
    InvalidLastIrrigation,
    Suggestion,
    check_last_irrigation,
    past_days_requested,
    suggest,
)

# Tomato: L_ini 30, L_dev 40, L_mid 40, L_late 25 (season 135). Sand: 83 mm/m.
PLANTING = date(2026, 1, 1)
AW = 83.0


def day(i: int) -> date:
    """Calendar date of season day i."""
    return PLANTING + timedelta(days=i - 1)


def weather(first: int, last: int, et0: float = 5.0, rain: dict[int, float] | None = None):
    rain = rain or {}
    return [DayWeather(day(i), et0, rain.get(i, 0.0)) for i in range(first, last + 1)]


def run(today_i: int, last_i: int, past: list[DayWeather], crop: str = "tomato") -> Suggestion:
    return suggest(crop, PLANTING, AW, day(last_i), day(today_i), past)


# Day 80 is mid-season: Kc 1.15, Zr 0.70, TAW 83 * 0.70 = 58.10, ETc at ET0 5.0 = 5.75.
# Roots are at full depth from day 71 on (Zr hits Zmax when (i-1)/70 >= 1).


def test_case_4a():
    # cases.md 4a: 3 past days * 5.75 = 17.25 -> 1 - 17.25 / 58.10 = 0.7031
    s = run(80, 76, weather(77, 79))
    assert s == Suggestion(0.7031, True, None, 3, 3)


def test_case_4b():
    # cases.md 4b: 14 days * 5.75 = 80.5 > TAW, Dr capped at 58.10 -> 0.0
    s = run(80, 65, weather(66, 79))
    assert s.value == 0.0
    assert s.exact is True
    assert s.reason is None
    assert (s.past_days_requested, s.past_days_returned) == (14, 14)


def test_taw_grows_uses_todays_taw():
    # I14. Today = day 40 (dev), D = day 36, past days 37, 38, 39, ET0 5.0.
    # Kc(i) = 0.60 + (i - 30) / 40 * 0.55:
    #   37: 0.69625, 38: 0.71000, 39: 0.72375 -> ETc 3.48125 + 3.55 + 3.61875 = 10.65
    # TAW(i) = 83 * (0.20 + 0.50 * (i - 1) / 70): TAW(39) = 39.1286, TAW(40) = 39.7214
    # No day reaches the cap, so Dr = 10.65.
    # Today's TAW: 1 - 10.65 / 39.7214 = 0.73188 -> 0.7319 (day 39's TAW would give 0.7278).
    s = run(40, 36, weather(37, 39))
    assert s.value == 0.7319


@pytest.mark.parametrize("last_i", [80, 79])
def test_d_today_and_yesterday(last_i):
    # I22: nothing to simulate -> bucket full.
    s = run(80, last_i, [])
    assert s == Suggestion(1.0, True, None, 0, 0)


def test_all_days_returned_start_full_after_irrigation():
    # D = 78: only day 79 is simulated: Dr 5.75 -> 1 - 5.75 / 58.10 = 0.9010
    s = run(80, 78, weather(79, 79))
    assert s.value == 0.901


def test_fewer_days_not_reaching_empty():
    # D = day 65 asks for 14 days, only 77..79 come back: 3 * 5.75 = 17.25 < TAW, never empty.
    s = run(80, 65, weather(77, 79))
    assert s == Suggestion(None, False, "insufficient_past_weather", 14, 3)


def test_fewer_days_reaching_empty():
    # 12 days returned (68..79) from a full bucket: 10 days = 57.5 < TAW(77) 58.10,
    # day 78 = 63.25 -> capped at 58.10 (empty). Day 79 stays at the cap. Value 0.0, exact.
    s = run(80, 65, weather(68, 79))
    assert s == Suggestion(0.0, True, None, 14, 12)


def test_fewer_days_reaching_empty_then_rain_is_above_zero():
    # As above, plus 20 mm of rain on day 79 (>= 0.2 * 5.0).
    # Day 78: Dr = 58.10 (empty). Day 79: max(58.10 - 20, 0) + 5.75 = 43.85.
    # 1 - 43.85 / 58.10 = 0.24527 -> 0.2453
    s = run(80, 65, weather(68, 79, rain={79: 20.0}))
    assert s == Suggestion(0.2453, True, None, 14, 12)


def test_zero_returned():
    s = run(80, 70, [])
    assert s == Suggestion(None, False, "insufficient_past_weather", 9, 0)


def test_rain_in_past_days():
    # I16. D = 76, days 77..79, rain on day 78.
    # Rain 1.0 >= 0.2 * 5.0: Dr 5.75 -> max(5.75 - 1.0, 0) + 5.75 = 10.50 -> 16.25
    #   1 - 16.25 / 58.10 = 0.72031 -> 0.7203
    assert run(80, 76, weather(77, 79, rain={78: 1.0})).value == 0.7203
    # Rain 0.5 < 1.0 is ignored: Dr 17.25 -> 0.7031 (same as case 4a).
    assert run(80, 76, weather(77, 79, rain={78: 0.5})).value == 0.7031


def test_rain_beyond_full_drains_away():
    # Day 77: Dr 5.75. Day 78: rain 30 -> max(5.75 - 30, 0) + 5.75 = 5.75. Day 79: 11.50.
    # 1 - 11.50 / 58.10 = 0.80207 -> 0.8021
    assert run(80, 76, weather(77, 79, rain={78: 30.0})).value == 0.8021


def test_season_ended():
    # I18: today = day 136 (season is 135 days).
    s = run(136, 130, weather(131, 135))
    assert s.value is None
    assert s.exact is False
    assert s.reason == "season_ended"


def test_pepper_uses_its_own_crop_table():
    # Pepper (30/35/40/20, Kc_ini 0.60, Kc_mid 1.05, Zmax 0.50), today = day 80 (mid).
    # Zr 0.50 from day 66 on -> TAW 41.5. D = day 78: day 79 ETc = 1.05 * 5 = 5.25.
    # 1 - 5.25 / 41.5 = 0.87349 -> 0.8735
    s = run(80, 78, weather(79, 79), crop="bell-pepper")
    assert s.value == 0.8735


def test_check_last_irrigation_valid_edges():
    today = day(80)
    for d in (today, today - timedelta(days=1), PLANTING):
        check_last_irrigation(d, today, PLANTING)  # no exception
    late = day(120)  # 92 days back is still after planting
    check_last_irrigation(late - timedelta(days=MAX_PAST_DAYS), late, PLANTING)


def test_check_last_irrigation_errors():
    today = day(80)
    with pytest.raises(InvalidLastIrrigation):
        check_last_irrigation(today + timedelta(days=1), today, PLANTING)
    late = day(120)
    with pytest.raises(InvalidLastIrrigation):
        check_last_irrigation(late - timedelta(days=MAX_PAST_DAYS + 1), late, PLANTING)
    with pytest.raises(InvalidLastIrrigation):
        check_last_irrigation(PLANTING - timedelta(days=1), day(20), PLANTING)


def test_past_days_requested():
    today = day(80)
    assert past_days_requested(today - timedelta(days=5), today) == 4
    assert past_days_requested(today, today) == 0
    assert past_days_requested(today - timedelta(days=1), today) == 0
