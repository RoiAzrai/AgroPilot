import sqlite3

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from conftest import assert_problem
from db import get_db
from errors import conflict, not_found, register_error_handlers, validation


@pytest.fixture
def probe(db_file) -> TestClient:
    """A throwaway app with the real handlers, to exercise each error path."""
    probe_app = FastAPI()
    register_error_handlers(probe_app)

    @probe_app.get("/not-found")
    def raise_not_found():
        raise not_found("Farm not found")

    @probe_app.get("/conflict")
    def raise_conflict():
        raise conflict("Farm still has plots")

    @probe_app.get("/validation")
    def raise_validation():
        raise validation("Unknown farm")

    @probe_app.get("/typed")
    def typed(n: int):
        return {"n": n}

    @probe_app.get("/duplicate-plot")
    def duplicate_plot(conn: sqlite3.Connection = Depends(get_db)):
        with conn:
            conn.execute(
                "INSERT INTO plots SELECT ?, farm_id, name, area_m2, crop_id, planting_date,"
                " soil_id, row_spacing_m, emitter_spacing_m, emitter_id, lat, lon"
                " FROM plots WHERE name = 'North block'",
                ("00000000-0000-4000-8000-000000000000",),
            )

    @probe_app.get("/foreign-key")
    def foreign_key(conn: sqlite3.Connection = Depends(get_db)):
        with conn:
            conn.execute("DELETE FROM farms")

    return TestClient(probe_app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("path", "status", "code", "detail"),
    [
        ("/not-found", 404, "NOT_FOUND", "Farm not found"),
        ("/conflict", 409, "CONFLICT", "Farm still has plots"),
        ("/validation", 422, "VALIDATION", "Unknown farm"),
    ],
)
def test_app_error_renders_problem_json(probe, path, status, code, detail):
    body = assert_problem(probe.get(path), status, code)
    assert body["detail"] == detail


def test_app_error_title_is_the_reason_phrase(probe):
    assert probe.get("/validation").json()["title"] == "Unprocessable Entity"


def test_request_validation_error_is_422(probe):
    body = assert_problem(probe.get("/typed", params={"n": "abc"}), 422, "VALIDATION")
    assert "query.n" in body["detail"]


def test_unique_violation_is_409(probe, db_file):
    body = assert_problem(probe.get("/duplicate-plot"), 409, "CONFLICT")
    assert body["detail"] == "A plot with this name already exists in this farm"
    conn = sqlite3.connect(db_file)
    assert conn.execute("SELECT COUNT(*) FROM plots").fetchone()[0] == 4
    conn.close()


def test_foreign_key_violation_is_not_mapped_globally(probe):
    response = probe.get("/foreign-key")
    assert response.status_code == 500
    assert response.headers["content-type"] != "application/problem+json"


def test_unknown_route_is_404(client):
    body = assert_problem(client.get("/v1/nothing-here"), 404, "NOT_FOUND")
    assert body["detail"] == "No route matches /v1/nothing-here"


def test_wrong_method_is_405(client):
    response = client.post("/health")
    body = assert_problem(response, 405, "VALIDATION")
    assert body["title"] == "Method Not Allowed"
    assert body["detail"] == "POST is not allowed on /health"
    assert response.headers["allow"] == "GET"


def test_health_is_unchanged(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok"}
