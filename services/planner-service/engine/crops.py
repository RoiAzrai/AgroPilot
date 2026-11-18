from dataclasses import dataclass


@dataclass(frozen=True)
class Crop:
    l_ini: int
    l_dev: int
    l_mid: int
    l_late: int
    kc_ini: float
    kc_mid: float
    kc_end: float
    zmax: float
    p: float

    @property
    def season_length(self) -> int:
        return self.l_ini + self.l_dev + self.l_mid + self.l_late


# Keyed by registry crop id. FAO-56 Tables 11, 12, 22 (see the skill).
CROPS: dict[str, Crop] = {
    "tomato": Crop(30, 40, 40, 25, 0.60, 1.15, 0.80, 0.70, 0.40),
    "bell-pepper": Crop(30, 35, 40, 20, 0.60, 1.05, 0.90, 0.50, 0.30),
}


class UnknownCrop(KeyError):
    pass


def get_crop(crop_id: str) -> Crop:
    try:
        return CROPS[crop_id]
    except KeyError:
        raise UnknownCrop(crop_id) from None
