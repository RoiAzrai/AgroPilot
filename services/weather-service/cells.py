import math
from decimal import Decimal

Cell = tuple[int, int]


def cell_of(lat: float, lon: float) -> Cell:
    return (
        math.floor(Decimal(str(lat)) * 10),
        math.floor(Decimal(str(lon)) * 10),
    )


def _center(index: int, limit: int) -> float:
    return round(max(-limit, min(limit, index / 10 + 0.05)), 2)


def cell_center(cell: Cell) -> tuple[float, float]:
    return _center(cell[0], 90), _center(cell[1], 180)
