from datetime import date

import pytest

from engine.crops import CROPS, UnknownCrop, get_crop
from engine.season import kc, root_depth, season_day, stage

TOMATO = CROPS["tomato"]
PEPPER = CROPS["bell-pepper"]


def test_season_day_counts_planting_day_as_one():
    planting = date(2026, 3, 1)
    assert season_day(planting, planting) == 1
    assert season_day(date(2026, 3, 2), planting) == 2


def test_season_day_before_planting_is_below_one():
    assert season_day(date(2026, 2, 28), date(2026, 3, 1)) == 0


@pytest.mark.parametrize(
    "i, expected",
    [
        (0, "not_planted"), (-5, "not_planted"),
        (1, "ini"), (30, "ini"),
        (31, "dev"), (70, "dev"),
        (71, "mid"), (110, "mid"),
        (111, "late"), (135, "late"),
        (136, "ended"),
    ],
)
def test_stage_boundaries_tomato(i, expected):
    assert stage(TOMATO, i) == expected


def test_season_length():
    assert TOMATO.season_length == 135
    assert PEPPER.season_length == 125


def test_kc_tomato_mid_is_constant():
    assert kc(TOMATO, 80) == 1.15


def test_kc_ini_is_constant():
    assert kc(TOMATO, 1) == 0.60
    assert kc(TOMATO, 30) == 0.60


def test_kc_tomato_end_of_season():
    assert kc(TOMATO, 135) == pytest.approx(0.80)


def test_kc_pepper_dev_case2_day1():
    assert kc(PEPPER, 40) == pytest.approx(0.7286, abs=5e-5)


def test_kc_pepper_dev_case2_day5():
    assert kc(PEPPER, 44) == pytest.approx(0.7800, abs=5e-5)


def test_root_depth_pepper_case2_day1():
    assert root_depth(PEPPER, 40) == pytest.approx(0.38)


def test_root_depth_pepper_case2_day2():
    assert root_depth(PEPPER, 41) == pytest.approx(0.3846, abs=5e-5)


def test_root_depth_tomato_full_depth_is_capped():
    assert root_depth(TOMATO, 80) == 0.70


def test_root_depth_planting_day_is_0_20():
    assert root_depth(TOMATO, 1) == 0.20


def test_get_crop_by_registry_id():
    assert get_crop("bell-pepper") is PEPPER
    assert get_crop("tomato") is TOMATO


def test_get_crop_rejects_skill_name_pepper():
    with pytest.raises(UnknownCrop):
        get_crop("pepper")


@pytest.mark.parametrize("i", [0, -5])
def test_root_depth_before_planting_raises(i):
    with pytest.raises(ValueError):
        root_depth(TOMATO, i)
