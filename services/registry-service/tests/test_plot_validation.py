from datetime import date, datetime, timedelta, timezone

import pytest

import models
from conftest import assert_problem
from test_plots import EAST_BLOCK, GREENHOUSE, NORTH_BLOCK, SPEC_BODY, WEST_BLOCK

# In the past, so "one day later" is rejected only because the clock is pinned.
FIXED_LATEST_DATE = date(2026, 6, 15)
SUCCESS = {"POST": 201, "PATCH": 200}


@pytest.fixture
def fixed_clock(monkeypatch):
    """Pin latest_date_on_earth() to FIXED_LATEST_DATE."""
    monkeypatch.setattr(models, "latest_date_on_earth", lambda: FIXED_LATEST_DATE)


def submit(client, method, changes):
    """POST the spec body with changes applied, or PATCH the changes onto North block."""
    if method == "POST":
        return client.post("/v1/plots", json={**SPEC_BODY, **changes})
    return client.patch(f"/v1/plots/{NORTH_BLOCK}", json=changes)


def assert_rejected(client, method, changes) -> dict:
    before = client.get("/v1/plots").json()
    body = assert_problem(submit(client, method, changes), 422, "VALIDATION")
    assert client.get("/v1/plots").json() == before
    return body


def assert_accepted(client, method, changes):
    response = submit(client, method, changes)
    assert response.status_code == SUCCESS[method], response.json()
    for field, value in changes.items():
        assert response.json()[field] == value


methods = pytest.mark.parametrize("method", ["POST", "PATCH"])
positive_fields = pytest.mark.parametrize(
    "field", ["area_m2", "row_spacing_m", "emitter_spacing_m"]
)


@methods
@positive_fields
@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_size_is_rejected(client, method, field, value):
    assert_rejected(client, method, {field: value})


@methods
@positive_fields
def test_small_positive_size_is_accepted(client, method, field):
    assert_accepted(client, method, {field: 0.001})


@methods
@pytest.mark.parametrize(("field", "limit"), [("lat", 90), ("lon", 180)])
@pytest.mark.parametrize("sign", [-1, 1])
def test_coordinate_at_limit_is_accepted(client, method, field, limit, sign):
    assert_accepted(client, method, {field: sign * limit})


@methods
@pytest.mark.parametrize(("field", "limit"), [("lat", 90), ("lon", 180)])
@pytest.mark.parametrize("sign", [-1, 1])
def test_coordinate_past_limit_is_rejected(client, method, field, limit, sign):
    assert_rejected(client, method, {field: sign * (limit + 0.0001)})


@methods
def test_planting_date_equal_to_latest_date_is_accepted(client, fixed_clock, method):
    assert_accepted(client, method, {"planting_date": FIXED_LATEST_DATE.isoformat()})


@methods
@pytest.mark.parametrize(
    "planting_date",
    [(FIXED_LATEST_DATE + timedelta(days=1)).isoformat(), "2027-01-01"],
    ids=["one-day-later", "clearly-future"],
)
def test_future_planting_date_is_rejected(client, fixed_clock, method, planting_date):
    body = assert_rejected(client, method, {"planting_date": planting_date})
    assert body["detail"] == "body.planting_date: cannot be in the future"


@methods
def test_israel_after_midnight_is_accepted(client, monkeypatch, method):
    # 22:30 UTC on Nov 3 is 00:30 on Nov 4 in Israel; UTC alone would reject Nov 4.
    instant = datetime(2026, 11, 3, 22, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(models, "_utc_now", lambda: instant)
    assert_accepted(client, method, {"planting_date": "2026-11-04"})


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc), date(2026, 11, 4)),
        (datetime(2026, 11, 3, 9, 59, tzinfo=timezone.utc), date(2026, 11, 3)),
        (datetime(2026, 11, 3, 22, 30, tzinfo=timezone.utc), date(2026, 11, 4)),
    ],
)
def test_latest_date_on_earth_is_the_utc_plus_14_date(monkeypatch, instant, expected):
    monkeypatch.setattr(models, "_utc_now", lambda: instant)
    assert models.latest_date_on_earth() == expected


def test_real_clock_is_within_bounds():
    # Bounded, not a single equality: the date may roll over between the reads.
    before = datetime.now(models.UTC_PLUS_14).date()
    result = models.latest_date_on_earth()
    after = datetime.now(models.UTC_PLUS_14).date()
    assert result in {before, after}


@pytest.mark.parametrize("plot_id", [NORTH_BLOCK, EAST_BLOCK, WEST_BLOCK, GREENHOUSE])
def test_every_seeded_plot_still_passes(client, plot_id):
    assert client.patch(f"/v1/plots/{plot_id}", json={}).status_code == 200


def test_spec_example_body_is_still_created(client):
    response = client.post("/v1/plots", json=SPEC_BODY)
    assert response.status_code == 201
    assert response.json() == {**SPEC_BODY, "id": response.json()["id"]}


@methods
def test_error_detail_names_field_and_rule(client, method):
    body = assert_rejected(client, method, {"area_m2": 0})
    assert body["detail"] == "body.area_m2: Input should be greater than 0"
