import sqlite3
from uuid import UUID, uuid4

import pytest

from conftest import assert_problem

DEMO_COOPERATIVE = "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001"
EAST_FARM = "a9c1e4b2-6f70-4d8e-a144-3f8b5c904004"


def test_list_returns_seeded_farms(client):
    response = client.get("/v1/farms")
    assert response.status_code == 200
    assert response.json() == [
        {"id": DEMO_COOPERATIVE, "name": "Demo cooperative"},
        {"id": EAST_FARM, "name": "East farm"},
    ]


def test_get_seeded_farm(client):
    response = client.get(f"/v1/farms/{EAST_FARM}")
    assert response.status_code == 200
    assert response.json() == {"id": EAST_FARM, "name": "East farm"}


def test_get_accepts_uppercase_id(client):
    response = client.get(f"/v1/farms/{DEMO_COOPERATIVE.upper()}")
    assert response.status_code == 200
    assert response.json()["id"] == DEMO_COOPERATIVE


def test_create_farm(client):
    response = client.post("/v1/farms", json={"name": "South farm"})
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "name"}
    assert body["name"] == "South farm"
    UUID(body["id"])
    assert client.get(f"/v1/farms/{body['id']}").json() == body


def test_create_strips_name(client):
    body = client.post("/v1/farms", json={"name": "  South farm  "}).json()
    assert body["name"] == "South farm"
    assert client.get(f"/v1/farms/{body['id']}").json()["name"] == "South farm"


def test_farm_names_do_not_have_to_be_unique(client):
    first = client.post("/v1/farms", json={"name": "Twin farm"})
    second = client.post("/v1/farms", json={"name": "Twin farm"})
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


@pytest.mark.parametrize(
    "body",
    [
        {"id": str(uuid4()), "name": "South farm"},
        {"name": "South farm", "owner": "someone"},
        {},
        {"name": ""},
        {"name": "   "},
        {"name": None},
        {"name": 42},
    ],
    ids=["id-in-body", "unknown-field", "missing-name", "empty", "whitespace", "null", "number"],
)
def test_create_rejects_invalid_body(client, body):
    assert_problem(client.post("/v1/farms", json=body), 422, "VALIDATION")
    assert len(client.get("/v1/farms").json()) == 2


def test_patch_renames_farm(client):
    response = client.patch(f"/v1/farms/{EAST_FARM}", json={"name": "  West farm "})
    assert response.status_code == 200
    assert response.json() == {"id": EAST_FARM, "name": "West farm"}
    assert client.get(f"/v1/farms/{EAST_FARM}").json()["name"] == "West farm"


def test_patch_empty_body_leaves_farm_unchanged(client):
    response = client.patch(f"/v1/farms/{EAST_FARM}", json={})
    assert response.status_code == 200
    assert response.json() == {"id": EAST_FARM, "name": "East farm"}


@pytest.mark.parametrize(
    "body",
    [{"name": None}, {"name": "  "}, {"id": str(uuid4())}, {"owner": "someone"}],
    ids=["null", "whitespace", "id-in-body", "unknown-field"],
)
def test_patch_rejects_invalid_body(client, body):
    assert_problem(client.patch(f"/v1/farms/{EAST_FARM}", json=body), 422, "VALIDATION")
    assert client.get(f"/v1/farms/{EAST_FARM}").json()["name"] == "East farm"


def test_delete_new_farm(client):
    farm_id = client.post("/v1/farms", json={"name": "Short-lived farm"}).json()["id"]
    response = client.delete(f"/v1/farms/{farm_id}")
    assert response.status_code == 204
    assert response.content == b""
    assert_problem(client.get(f"/v1/farms/{farm_id}"), 404, "NOT_FOUND")


def test_delete_farm_with_plots_is_409(client, db_file):
    body = assert_problem(client.delete(f"/v1/farms/{DEMO_COOPERATIVE}"), 409, "CONFLICT")
    assert body["detail"] == "Farm has plots; delete or move them first"
    assert client.get(f"/v1/farms/{DEMO_COOPERATIVE}").status_code == 200
    conn = sqlite3.connect(db_file)
    plots = conn.execute(
        "SELECT COUNT(*) FROM plots WHERE farm_id = ?", (DEMO_COOPERATIVE,)
    ).fetchone()[0]
    conn.close()
    assert plots == 2


@pytest.mark.parametrize("farm_id", [str(uuid4()), "abc"], ids=["unknown", "not-a-uuid"])
@pytest.mark.parametrize(
    ("method", "body"),
    [("GET", None), ("PATCH", {"name": "Renamed"}), ("DELETE", None)],
)
def test_unknown_or_malformed_id_is_404(client, farm_id, method, body):
    response = client.request(method, f"/v1/farms/{farm_id}", json=body)
    assert_problem(response, 404, "NOT_FOUND")
