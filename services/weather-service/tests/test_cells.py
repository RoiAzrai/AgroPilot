import pytest

from cells import cell_center, cell_of


@pytest.mark.parametrize(
    ("lat", "lon", "expected"),
    [
        (31.25, 34.79, (312, 347)),
        (31.3, 0, (313, 0)),
        (-0.05, -0.05, (-1, -1)),
        (-0.0, 0.0, (0, 0)),
        (0.1 + 0.2, 0, (3, 0)),
        (-33.95, 151.2, (-340, 1512)),
        (90, 180, (900, 1800)),
        (-90, -180, (-900, -1800)),
    ],
)
def test_cell_of(lat, lon, expected):
    assert cell_of(lat, lon) == expected


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ((312, 347), (31.25, 34.75)),
        ((900, 1800), (90.0, 180.0)),
        ((-900, -1800), (-89.95, -179.95)),
        ((-1, -1), (-0.05, -0.05)),
    ],
)
def test_cell_center(cell, expected):
    assert cell_center(cell) == expected
