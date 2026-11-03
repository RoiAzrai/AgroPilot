from uuid import UUID, uuid4

import pytest

from conftest import assert_problem

DEMO_COOPERATIVE = "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001"
EAST_FARM = "a9c1e4b2-6f70-4d8e-a144-3f8b5c904004"
NORTH_BLOCK = "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002"  # Demo cooperative
EAST_BLOCK = "d9a4e2c1-5e3f-4b6a-9c33-2e7f4a803003"  # Demo cooperative
WEST_BLOCK = "e0b5f3d2-6f40-4c7b-8d44-3f8a5b914004"  # East farm
GREENHOUSE = "f1c6a4e3-7051-4d8c-9e55-4a9b6c025005"  # East farm

PLOT_KEYS = {
    "id", "farm_id", "name", "area_m2", "crop_id", "planting_date", "soil_id",
    "row_spacing_m", "emitter_spacing_m", "emitter_id", "lat", "lon",
}

# The POST /v1/plots example from docs/task-p1.md, unchanged.
SPEC_BODY = {
    "farm_id": "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001",
    "name": "South block",
    "area_m2": 1000,
    "crop_id": "tomato",
    "planting_date": "2026-03-01",
    "soil_id": "loam",
    "row_spacing_m": 1.5,
    "emitter_spacing_m": 0.4,
    "emitter_id": "dripnet-pc-1.0",
    "lat": 31.25,
    "lon": 34.79,
}


@pytest.fixture
def all_plots(client):
    """Returns a function that reads every plot, to prove a rejected write changed nothing."""
    return lambda: client.get("/v1/plots").json()


def test_list_returns_seeded_plots(client):
    response = client.get("/v1/plots")
    assert response.status_code == 200
    plots = response.json()
    assert [plot["id"] for plot in plots] == [NORTH_BLOCK, EAST_BLOCK, WEST_BLOCK, GREENHOUSE]
    assert all(set(plot) == PLOT_KEYS for plot in plots)


def test_get_seeded_plot(client):
    response = client.get(f"/v1/plots/{NORTH_BLOCK.upper()}")
    assert response.status_code == 200
    assert response.json() == {
        "id": NORTH_BLOCK,
        "farm_id": DEMO_COOPERATIVE,
        "name": "North block",
        "area_m2": 1000,
        "crop_id": "tomato",
        "planting_date": "2026-03-01",
        "soil_id": "loam",
        "row_spacing_m": 1.5,
        "emitter_spacing_m": 0.4,
        "emitter_id": "dripnet-pc-1.0",
        "lat": 31.25,
        "lon": 34.79,
    }


@pytest.mark.parametrize(
    ("farm_id", "expected"),
    [(DEMO_COOPERATIVE, {NORTH_BLOCK, EAST_BLOCK}), (EAST_FARM, {WEST_BLOCK, GREENHOUSE})],
)
def test_filter_by_farm(client, farm_id, expected):
    response = client.get("/v1/plots", params={"farm_id": farm_id})
    assert response.status_code == 200
    assert {plot["id"] for plot in response.json()} == expected


def test_filter_by_unknown_farm_is_empty(client):
    response = client.get("/v1/plots", params={"farm_id": str(uuid4())})
    assert response.status_code == 200
    assert response.json() == []


def test_filter_by_new_farm_without_plots_is_empty(client):
    farm_id = client.post("/v1/farms", json={"name": "Empty farm"}).json()["id"]
    assert client.get("/v1/plots", params={"farm_id": farm_id}).json() == []


def test_filter_by_malformed_farm_id_is_422(client):
    assert_problem(client.get("/v1/plots", params={"farm_id": "abc"}), 422, "VALIDATION")


def test_create_with_spec_body(client):
    response = client.post("/v1/plots", json=SPEC_BODY)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == PLOT_KEYS
    UUID(body["id"])
    assert body == {**SPEC_BODY, "id": body["id"]}
    assert client.get(f"/v1/plots/{body['id']}").json() == body


def test_create_normalizes_farm_id_and_name(client):
    body = {**SPEC_BODY, "farm_id": DEMO_COOPERATIVE.upper(), "name": "  South block  "}
    created = client.post("/v1/plots", json=body).json()
    assert created["farm_id"] == DEMO_COOPERATIVE
    assert created["name"] == "South block"


@pytest.mark.parametrize(
    "body",
    [
        {key: value for key, value in SPEC_BODY.items() if key != "lat"},
        {**SPEC_BODY, "owner": "someone"},
        {**SPEC_BODY, "id": str(uuid4())},
        {**SPEC_BODY, "area_m2": "1000"},
        {**SPEC_BODY, "row_spacing_m": True},
        {**SPEC_BODY, "planting_date": "01/03/2026"},
        {**SPEC_BODY, "planting_date": "2026-02-30"},
        {**SPEC_BODY, "farm_id": "abc"},
        {**SPEC_BODY, "name": "   "},
        {**SPEC_BODY, "crop_id": None},
    ],
    ids=[
        "missing-field", "unknown-field", "id-in-body", "number-as-string",
        "boolean-as-number", "wrong-date-format", "impossible-date",
        "malformed-farm-id", "blank-name", "null-crop",
    ],
)
def test_create_rejects_invalid_body(client, all_plots, body):
    before = all_plots()
    assert_problem(client.post("/v1/plots", json=body), 422, "VALIDATION")
    assert all_plots() == before


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("farm_id", str(uuid4()), "Unknown farm"),
        ("crop_id", "cucumber", "Unknown crop"),
        ("soil_id", "peat", "Unknown soil"),
        ("emitter_id", "dripnet-pc-9.9", "Unknown emitter"),
    ],
)
def test_create_with_unknown_reference_is_422(client, all_plots, field, value, detail):
    before = all_plots()
    response = client.post("/v1/plots", json={**SPEC_BODY, field: value})
    assert assert_problem(response, 422, "VALIDATION")["detail"] == detail
    assert all_plots() == before


def test_duplicate_name_in_same_farm_is_409(client, all_plots):
    before = all_plots()
    response = client.post("/v1/plots", json={**SPEC_BODY, "name": "North block"})
    body = assert_problem(response, 409, "CONFLICT")
    assert body["detail"] == "A plot with this name already exists in this farm"
    assert all_plots() == before


def test_same_name_in_other_farm_is_allowed(client):
    response = client.post(
        "/v1/plots", json={**SPEC_BODY, "farm_id": EAST_FARM, "name": "North block"}
    )
    assert response.status_code == 201


def test_patch_changes_only_the_sent_field(client):
    before = client.get(f"/v1/plots/{NORTH_BLOCK}").json()
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={"area_m2": 1250})
    assert response.status_code == 200
    assert response.json() == {**before, "area_m2": 1250}
    assert client.get(f"/v1/plots/{NORTH_BLOCK}").json() == {**before, "area_m2": 1250}


def test_patch_empty_body_leaves_plot_unchanged(client):
    before = client.get(f"/v1/plots/{NORTH_BLOCK}").json()
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={})
    assert response.status_code == 200
    assert response.json() == before


def test_patch_rename_to_existing_name_in_same_farm_is_409(client, all_plots):
    before = all_plots()
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={"name": "East block"})
    assert_problem(response, 409, "CONFLICT")
    assert all_plots() == before


def test_patch_move_to_farm_that_has_the_name_is_409(client, all_plots):
    client.post("/v1/plots", json={**SPEC_BODY, "farm_id": EAST_FARM, "name": "North block"})
    before = all_plots()
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={"farm_id": EAST_FARM})
    assert_problem(response, 409, "CONFLICT")
    assert all_plots() == before


def test_patch_move_to_farm_without_the_name(client):
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json={"farm_id": EAST_FARM})
    assert response.status_code == 200
    assert response.json()["farm_id"] == EAST_FARM
    moved = client.get("/v1/plots", params={"farm_id": EAST_FARM}).json()
    assert NORTH_BLOCK in {plot["id"] for plot in moved}


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"farm_id": str(uuid4())}, "Unknown farm"),
        ({"crop_id": "cucumber"}, "Unknown crop"),
        ({"soil_id": "peat"}, "Unknown soil"),
        ({"emitter_id": "dripnet-pc-9.9"}, "Unknown emitter"),
    ],
)
def test_patch_with_unknown_reference_is_422(client, all_plots, body, detail):
    before = all_plots()
    response = client.patch(f"/v1/plots/{NORTH_BLOCK}", json=body)
    assert assert_problem(response, 422, "VALIDATION")["detail"] == detail
    assert all_plots() == before


@pytest.mark.parametrize(
    "body",
    [
        {"name": None},
        {"area_m2": "1250"},
        {"lat": False},
        {"planting_date": "2026/03/01"},
        {"id": str(uuid4())},
        {"owner": "someone"},
    ],
    ids=["null-name", "number-as-string", "boolean-as-number", "wrong-date-format",
         "id-in-body", "unknown-field"],
)
def test_patch_rejects_invalid_body(client, all_plots, body):
    before = all_plots()
    assert_problem(client.patch(f"/v1/plots/{NORTH_BLOCK}", json=body), 422, "VALIDATION")
    assert all_plots() == before


def test_delete_plot(client):
    response = client.delete(f"/v1/plots/{GREENHOUSE}")
    assert response.status_code == 204
    assert response.content == b""
    assert_problem(client.get(f"/v1/plots/{GREENHOUSE}"), 404, "NOT_FOUND")


def test_farm_can_be_deleted_once_its_plots_are_gone(client):
    assert_problem(client.delete(f"/v1/farms/{EAST_FARM}"), 409, "CONFLICT")
    for plot_id in (WEST_BLOCK, GREENHOUSE):
        assert client.delete(f"/v1/plots/{plot_id}").status_code == 204
    assert client.delete(f"/v1/farms/{EAST_FARM}").status_code == 204
    assert_problem(client.get(f"/v1/farms/{EAST_FARM}"), 404, "NOT_FOUND")


@pytest.mark.parametrize("plot_id", [str(uuid4()), "abc"], ids=["unknown", "not-a-uuid"])
@pytest.mark.parametrize(
    ("method", "body"),
    [("GET", None), ("PATCH", {"name": "Renamed"}), ("DELETE", None)],
)
def test_unknown_or_malformed_id_is_404(client, plot_id, method, body):
    response = client.request(method, f"/v1/plots/{plot_id}", json=body)
    assert_problem(response, 404, "NOT_FOUND")
