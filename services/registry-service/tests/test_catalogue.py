import sqlite3

import pytest

from conftest import assert_problem

CROPS = [
    {"id": "tomato", "name": "Tomato"},
    {"id": "bell-pepper", "name": "Bell pepper"},
]
SOILS = [
    {"id": "sand", "name": "Sand", "available_water_mm_per_m": 83},
    {"id": "loam", "name": "Loam", "available_water_mm_per_m": 175},
    {"id": "clay-loam", "name": "Clay loam", "available_water_mm_per_m": 200},
]
EMITTERS = [
    {"id": "dripnet-pc-0.6", "name": "DripNet PC", "flow_lph": 0.6},
    {"id": "dripnet-pc-1.0", "name": "DripNet PC", "flow_lph": 1.0},
    {"id": "dripnet-pc-1.6", "name": "DripNet PC", "flow_lph": 1.6},
    {"id": "dripnet-pc-2.0", "name": "DripNet PC", "flow_lph": 2.0},
]

ROUTES = [
    "/v1/crops", "/v1/crops/tomato",
    "/v1/soils", "/v1/soils/sand",
    "/v1/emitters", "/v1/emitters/dripnet-pc-1.0",
]


def catalogue_rows(db_file) -> dict[str, list[tuple]]:
    conn = sqlite3.connect(db_file)
    rows = {
        table: conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        for table in ("crops", "soils", "emitters")
    }
    conn.close()
    return rows


@pytest.mark.parametrize(
    ("path", "expected"),
    [("/v1/crops", CROPS), ("/v1/soils", SOILS), ("/v1/emitters", EMITTERS)],
)
def test_list_returns_seed_rows(client, path, expected):
    response = client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert body == expected
    assert all(set(item) == set(expected[0]) for item in body)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/v1/crops/tomato", {"id": "tomato", "name": "Tomato"}),
        ("/v1/soils/sand", {"id": "sand", "name": "Sand", "available_water_mm_per_m": 83}),
        (
            "/v1/emitters/dripnet-pc-1.0",
            {"id": "dripnet-pc-1.0", "name": "DripNet PC", "flow_lph": 1.0},
        ),
    ],
)
def test_spec_examples(client, path, expected):
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == expected


def test_flow_lph_is_always_a_float(client):
    emitters = client.get("/v1/emitters").json()
    assert all(type(emitter["flow_lph"]) is float for emitter in emitters)
    assert '"flow_lph":1.0' in client.get("/v1/emitters/dripnet-pc-1.0").text


def test_available_water_is_always_an_int(client):
    soils = client.get("/v1/soils").json()
    assert all(type(soil["available_water_mm_per_m"]) is int for soil in soils)


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        ("/v1/crops/cucumber", "Crop not found"),
        ("/v1/crops/Tomato", "Crop not found"),
        ("/v1/soils/peat", "Soil not found"),
        ("/v1/soils/SAND", "Soil not found"),
        ("/v1/emitters/dripnet-pc-9.9", "Emitter not found"),
        ("/v1/emitters/DripNet-PC-1.0", "Emitter not found"),
    ],
)
def test_unknown_or_wrong_case_id_is_404(client, path, detail):
    assert assert_problem(client.get(path), 404, "NOT_FOUND")["detail"] == detail


@pytest.mark.parametrize("path", ROUTES)
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_write_methods_are_405(client, method, path):
    response = client.request(method, path, json={"id": "cucumber", "name": "Cucumber"})
    assert_problem(response, 405, "VALIDATION")
    assert "GET" in response.headers["allow"]


def test_catalogue_unchanged_after_write_attempts(client, db_file):
    before = catalogue_rows(db_file)
    for path in ROUTES:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            client.request(method, path, json={"id": "cucumber", "name": "Cucumber"})
    assert catalogue_rows(db_file) == before
    assert client.get("/v1/crops").json() == CROPS
    assert client.get("/v1/soils").json() == SOILS
    assert client.get("/v1/emitters").json() == EMITTERS
