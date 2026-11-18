from datetime import date

from engine.crops import Crop


def season_day(day: date, planting_date: date) -> int:
    """The planting day is day 1."""
    return (day - planting_date).days + 1


def stage(crop: Crop, i: int) -> str:
    if i < 1:
        return "not_planted"
    if i <= crop.l_ini:
        return "ini"
    if i <= crop.l_ini + crop.l_dev:
        return "dev"
    if i <= crop.l_ini + crop.l_dev + crop.l_mid:
        return "mid"
    if i <= crop.season_length:
        return "late"
    return "ended"


def kc(crop: Crop, i: int) -> float:
    """FAO-56 Eq. 66. Only defined for planted days inside the season."""
    s = stage(crop, i)
    if s in ("not_planted", "ended"):
        raise ValueError(f"no Kc for stage {s!r} (day {i})")
    if s == "ini":
        return crop.kc_ini
    if s == "dev":
        return crop.kc_ini + (i - crop.l_ini) / crop.l_dev * (crop.kc_mid - crop.kc_ini)
    if s == "mid":
        return crop.kc_mid
    mid_end = crop.l_ini + crop.l_dev + crop.l_mid
    return crop.kc_mid + (i - mid_end) / crop.l_late * (crop.kc_end - crop.kc_mid)


def root_depth(crop: Crop, i: int) -> float:
    """Annex 8 Eq. 8-3, time-based."""
    return 0.20 + (crop.zmax - 0.20) * min(1, (i - 1) / (crop.l_ini + crop.l_dev))
