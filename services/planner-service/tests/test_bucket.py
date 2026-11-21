import pytest

from engine.bucket import bucket_mm, effective_rain, raw, step, taw
from engine.crops import CROPS
from engine.drip import cap_mm, litres, run_minutes
from engine.season import kc, root_depth

TOMATO = CROPS["tomato"]
PEPPER = CROPS["bell-pepper"]

# Defaults of the Task 4 plan: TAW 122.5, RAW 49, ET0 6.0, ETc 6.9, cap 40.
BIG = dict(et0_mm=6.0, etc_mm=6.9, taw_mm=122.5, raw_mm=49.0, cap_mm=40.0)


def run_plan(crop, aw, first_day, et0, rain, bucket_start, cap, p=None):
    """Seven days through step(); returns (list of StepResult, list of bucket_mm)."""
    p = crop.p if p is None else p
    taw0 = taw(aw, root_depth(crop, first_day))
    dr = (1 - bucket_start) * taw0
    refilling = False
    results, buckets = [], []
    for d in range(7):
        i = first_day + d
        taw_i = taw(aw, root_depth(crop, i))
        etc = kc(crop, i) * et0
        r = step(dr, rain.get(d + 1, 0.0), et0, etc, taw_i, raw(p, taw_i), cap, refilling)
        dr, refilling = r.dr_end, r.refilling
        results.append(r)
        buckets.append(bucket_mm(taw_i, r.dr_end))
    return results, buckets


# --- helpers ---------------------------------------------------------------

def test_taw_raw():
    assert taw(83, 0.70) == pytest.approx(58.10)
    assert raw(0.40, 58.10) == pytest.approx(23.24)


def test_rain_filter():
    assert effective_rain(0.5, 5.0) == 0
    assert effective_rain(1.0, 5.0) == 1.0  # boundary: >= 0.2 * ET0


def test_bucket_mm():
    assert bucket_mm(58.10, 5.75) == pytest.approx(52.35)


# --- single steps ----------------------------------------------------------

def test_no_irrigation_below_raw():
    r = step(36.75, 0, **BIG, refilling=False)
    assert r.irrigation_mm == 0
    assert r.dr_end == pytest.approx(43.65)
    assert r.refilling is False


def test_capped_day():
    r = step(43.65, 0, **BIG, refilling=False)
    assert r.irrigation_mm == 40
    assert r.dr_end == pytest.approx(10.55)
    assert r.refilling is True


def test_continuation_finishing_day():
    r = step(10.55, 0, **BIG, refilling=True)
    assert r.irrigation_mm == pytest.approx(17.45)
    assert r.dr_end == 0
    assert r.refilling is False


def test_continuation_forces_irrigation_below_raw():
    # 10.55 + 6.9 = 17.45 < RAW 49, yet refilling=True irrigates.
    assert step(10.55, 0, **BIG, refilling=False).irrigation_mm == 0
    assert step(10.55, 0, **BIG, refilling=True).irrigation_mm == pytest.approx(17.45)


def test_continuation_rain_lowers_need():
    r = step(10.55, 12.0, **BIG, refilling=True)
    assert r.irrigation_mm == pytest.approx(6.9)
    assert r.dr_end == 0


def test_below_cap_identical_to_old_rule():
    # Case 1 day 5: Dr_start 23.00 (4 days x 5.75), need 28.75 > RAW 23.24, cap 64 > need.
    # I = need = 28.75, Dr_end = 0.
    r = step(23.0, 0, 5.0, 5.75, 58.10, 23.24, 64.0, False)
    assert r.irrigation_mm == pytest.approx(28.75)
    assert r.dr_end == 0
    assert r.refilling is False


def test_dr_end_capped_at_taw():
    # need = 120 + 6.9 = 126.9; I = 1; need - I = 125.9 > TAW, so Dr_end = 122.5.
    r = step(120, 0, 6.0, 6.9, 122.5, 49.0, 1.0, False)
    assert r.dr_end == 122.5
    assert r.refilling is True


def test_rain_beyond_full():
    # Dr_start = max(3 - 12, 0) = 0; 0 + 6.9 < RAW; Dr_end = 6.9.
    r = step(3, 12.0, **BIG, refilling=False)
    assert r.irrigation_mm == 0
    assert r.dr_end == pytest.approx(6.9)


# --- depletion fraction p is a parameter -----------------------------------

def test_p_zero_irrigates_etc_every_day():
    # RAW = 0, so Dr_start + ETc > 0 every day. Dr_end is 0 each day,
    # so I = need = 0 + ETc = 5.75 every day.
    dr, refilling = 0.0, False
    for _ in range(7):
        r = step(dr, 0, 5.0, 5.75, 58.10, raw(0.0, 58.10), 64.0, refilling)
        assert r.irrigation_mm == pytest.approx(5.75)
        assert r.dr_end == 0
        dr, refilling = r.dr_end, r.refilling


def test_p_half_is_the_tasks_half():
    # TAW 58.10, RAW 29.05, ETc 5.75: Dr after days 1..5 is 5.75, 11.5, 17.25, 23.0, 28.75.
    # Day 5 need 28.75 <= 29.05: no irrigation. Day 6 need 34.5 > 29.05: irrigate 34.5.
    dr, refilling, irr = 0.0, False, []
    for _ in range(6):
        r = step(dr, 0, 5.0, 5.75, 58.10, raw(0.5, 58.10), 64.0, refilling)
        irr.append(r.irrigation_mm)
        dr, refilling = r.dr_end, r.refilling
    assert irr[:5] == [0, 0, 0, 0, 0]
    assert irr[5] == pytest.approx(34.5)


# --- edge cases (expected values derived by hand) --------------------------

def test_bucket_start_zero_big_cap():
    # Case 1 numbers, Dr_0 = TAW = 58.10. need = 58.10 + 5.75 = 63.85 > RAW.
    # cap 64 >= need: I = 63.85 (more than TAW; the day's ETc is also replaced),
    # Dr_end = min(0, TAW) = 0, bucket_mm = 58.10.
    r = step(58.10, 0, 5.0, 5.75, 58.10, 23.24, 64.0, False)
    assert r.irrigation_mm == pytest.approx(63.85)
    assert r.dr_end == 0
    assert bucket_mm(58.10, r.dr_end) == pytest.approx(58.10)


def test_bucket_start_zero_small_cap_never_below_zero():
    # Same, cap 10: I = 10, need - I = 53.85 <= TAW, Dr_end 53.85, bucket 4.25.
    r = step(58.10, 0, 5.0, 5.75, 58.10, 23.24, 10.0, False)
    assert r.dr_end == pytest.approx(53.85)
    assert bucket_mm(58.10, r.dr_end) == pytest.approx(4.25)
    # cap 1: need - I = 62.85 > TAW, so Dr_end = 58.10 and bucket_mm = 0, not negative.
    r = step(58.10, 0, 5.0, 5.75, 58.10, 23.24, 1.0, False)
    assert r.dr_end == 58.10
    assert bucket_mm(58.10, r.dr_end) == 0


def test_cap_smaller_than_etc_never_completes():
    # Case 1 numbers, cap 3 < ETc 5.75. Start Dr 20: need 25.75 > RAW 23.24, I = 3,
    # Dr_end 22.75. Each day Dr grows by 5.75 - 3 = 2.75, until 58.10 caps it
    # (20 + 2.75 * 14 = 58.5 > 58.10 on day 14). It never refills, never crashes.
    dr, refilling = 20.0, False
    for day in range(1, 21):
        r = step(dr, 0, 5.0, 5.75, 58.10, 23.24, 3.0, refilling)
        assert r.irrigation_mm == 3.0
        assert r.refilling is True
        assert r.dr_end == pytest.approx(min(20 + 2.75 * day, 58.10))
        dr, refilling = r.dr_end, r.refilling
    assert dr == 58.10


def test_rain_on_continuation_day_stops_it():
    # Day A: dr 43.65 -> I 40, Dr_end 10.55, refilling. Day B has 12 mm rain (>= 1.2):
    # Dr_start = 0, need 6.9, I 6.9, Dr_end 0, refilling False. Day C (no rain,
    # refilling False): need 6.9 < RAW, so no irrigation.
    a = step(43.65, 0, **BIG, refilling=False)
    b = step(a.dr_end, 12.0, **BIG, refilling=a.refilling)
    assert (b.irrigation_mm, b.dr_end, b.refilling) == (pytest.approx(6.9), 0, False)
    c = step(b.dr_end, 0, **BIG, refilling=b.refilling)
    assert c.irrigation_mm == 0
    assert c.dr_end == pytest.approx(6.9)


def test_dr_prev_above_taw_is_capped():
    # Dr_prev 130 > TAW 122.5, cap 1: need 136.9, I 1, need - I = 135.9 -> Dr_end 122.5.
    r = step(130, 0, 6.0, 6.9, 122.5, 49.0, 1.0, False)
    assert r.dr_end == 122.5
    assert bucket_mm(122.5, r.dr_end) == 0


# --- hand-calculated cases (cases.md) --------------------------------------

def test_case1():
    cap = cap_mm(1440, 1.6, 1.5, 0.4)
    res, buckets = run_plan(TOMATO, 83, 80, 5.0, {}, 1.0, cap)
    assert buckets == pytest.approx([52.35, 46.60, 40.85, 35.10, 58.10, 52.35, 46.60], abs=5e-3)
    assert [r.irrigation_mm > 0 for r in res] == [False] * 4 + [True] + [False] * 2
    assert res[4].irrigation_mm == pytest.approx(28.75)
    assert litres(res[4].irrigation_mm, 1000) == 28750
    assert run_minutes(res[4].irrigation_mm, 1.5, 0.4, 1.6) == 647


def test_case2():
    cap = cap_mm(1440, 2.0, 1.2, 0.3)
    res, buckets = run_plan(PEPPER, 83, 40, 4.0, {}, 1.0, cap)
    expected = [28.626, 26.043, 23.409, 32.689, 29.952, 27.164, 24.324]
    assert buckets == pytest.approx(expected, abs=1e-3)
    assert [r.irrigation_mm > 0 for r in res] == [False] * 3 + [True] + [False] * 3
    assert res[3].irrigation_mm == pytest.approx(11.9657, abs=1e-4)
    assert litres(res[3].irrigation_mm, 400) == 4786
    assert run_minutes(res[3].irrigation_mm, 1.2, 0.3, 2.0) == 129


def test_case3_rain():
    cap = cap_mm(1440, 1.6, 1.5, 0.4)
    # 0.5 mm on day 2 is ignored (< 1.0); 12 mm on day 4 counts.
    res, buckets = run_plan(TOMATO, 83, 80, 5.0, {2: 0.5, 4: 12.0}, 1.0, cap)
    assert buckets == pytest.approx([52.35, 46.60, 40.85, 47.10, 41.35, 35.60, 58.10], abs=5e-3)
    assert [r.irrigation_mm > 0 for r in res] == [False] * 6 + [True]
    assert res[6].irrigation_mm == pytest.approx(28.25)
    assert litres(res[6].irrigation_mm, 1000) == 28250
    assert run_minutes(res[6].irrigation_mm, 1.5, 0.4, 1.6) == 636


def test_case5_daily_cap():
    cap = cap_mm(1440, 1.0, 1.5, 0.4)
    assert cap == pytest.approx(40.0)
    res, buckets = run_plan(TOMATO, 175, 80, 6.0, {}, 0.7, cap)
    assert buckets == pytest.approx([78.85, 111.95, 122.50, 115.60, 108.70, 101.80, 94.90], abs=5e-3)
    irr = [r.irrigation_mm for r in res]
    assert [i > 0 for i in irr] == [False, True, True, False, False, False, False]
    assert [litres(i, 1000) for i in irr] == [0, 40000, 17450, 0, 0, 0, 0]
    assert [run_minutes(i, 1.5, 0.4, 1.0) for i in irr] == [0, 1440, 628, 0, 0, 0, 0]
