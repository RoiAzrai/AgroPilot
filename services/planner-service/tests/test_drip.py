import math

import pytest

from engine.drip import cap_mm, litres, round_half_up, round_half_up_places, run_minutes


def test_round_half_up_float_trap():
    assert 0.5005 * 1000 == 500.49999999999994
    assert round_half_up(0.5005 * 1000) == 501


def test_round_half_up_not_bankers():
    assert round(248.5) == 248  # why Python round() is not used
    assert round_half_up(248.5) == 249
    assert round_half_up(248.4) == 248
    assert round_half_up(2.5) == 3
    assert round_half_up(0.5) == 1
    assert round_half_up(0.0) == 0


def test_round_half_up_places():
    assert round_half_up_places(2.675, 2) == 2.68
    assert round_half_up_places(0.70315, 4) == 0.7032


def test_round_half_up_places_removes_float_noise_before_rounding():
    # 0.015 * 0.7 is exactly 0.0105 on paper, a true half at 3 places -> 0.011 (half up).
    # In floats it is 0.010499999999999999 (about 1e-18 below the half), so without the
    # round(x, 6) step Decimal(repr(x)) sits below the half and gives 0.010.
    x = 0.015 * 0.7
    assert x == 0.010499999999999999
    assert round_half_up_places(x, 3) == 0.011


def test_task_example():
    assert litres(6.9, 1000) == 6900
    assert run_minutes(6.9, 1.5, 0.4, 1.0) == 248


def test_case1_day5():
    assert litres(28.75, 1000) == 28750
    assert run_minutes(28.75, 1.5, 0.4, 1.6) == 647


def test_case2_day4():
    # minutes come from the unrounded I (129.230), not from the rounded litres
    assert litres(11.9657, 400) == 4786
    assert run_minutes(11.9657, 1.2, 0.3, 2.0) == 129


def test_case3_day7():
    assert litres(28.25, 1000) == 28250
    assert run_minutes(28.25, 1.5, 0.4, 1.6) == 636


def test_case5_cap_float_error():
    cap = cap_mm(1440, 1.0, 1.5, 0.4)
    assert cap == pytest.approx(40.0)
    assert litres(cap, 1000) == 40000
    assert run_minutes(cap, 1.5, 0.4, 1.0) == 1440


def test_case5_day3():
    assert litres(17.45, 1000) == 17450
    assert run_minutes(17.45, 1.5, 0.4, 1.0) == 628


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_raises(bad):
    with pytest.raises(ValueError):
        round_half_up(bad)
    with pytest.raises(ValueError):
        round_half_up_places(bad, 2)
    with pytest.raises(ValueError):
        litres(bad, 1000)
    with pytest.raises(ValueError):
        litres(5.0, bad)
    with pytest.raises(ValueError):
        run_minutes(bad, 1.5, 0.4, 1.0)
    with pytest.raises(ValueError):
        run_minutes(5.0, bad, 0.4, 1.0)
    with pytest.raises(ValueError):
        run_minutes(5.0, 1.5, bad, 1.0)
    with pytest.raises(ValueError):
        run_minutes(5.0, 1.5, 0.4, bad)
    with pytest.raises(ValueError):
        cap_mm(1440, bad, 1.5, 0.4)


@pytest.mark.parametrize("flow, row, emitter", [
    (0, 1.5, 0.4), (-1.0, 1.5, 0.4),
    (1.0, 0, 0.4), (1.0, -1.5, 0.4),
    (1.0, 1.5, 0), (1.0, 1.5, -0.4),
])
def test_non_positive_raises(flow, row, emitter):
    with pytest.raises(ValueError):
        run_minutes(5.0, row, emitter, flow)
    with pytest.raises(ValueError):
        cap_mm(1440, flow, row, emitter)
