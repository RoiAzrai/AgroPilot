import logging
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import db
from conftest import assert_problem
from main import app
from routers import farms
from test_farms import DEMO_COOPERATIVE
from test_plots import NORTH_BLOCK, SPEC_BODY

REQUESTS = [
    ("GET", "/v1/farms", None),
    ("GET", f"/v1/plots/{NORTH_BLOCK}", None),
    ("POST", "/v1/plots", SPEC_BODY),
    ("GET", "/v1/crops", None),
]


@pytest.fixture
def server(db_file) -> TestClient:
    """A client that turns server exceptions into responses, as a real server would."""
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def assert_unavailable(response) -> dict:
    body = assert_problem(response, 503, "UNAVAILABLE")
    assert body["title"] == "Service Unavailable"
    assert body["detail"] == "Database unavailable"
    assert response.headers["retry-after"] == "5"
    return body


def assert_internal_error(response) -> dict:
    body = assert_problem(response, 500, "UNAVAILABLE")
    assert body["title"] == "Internal Server Error"
    assert body["detail"] == "Internal server error"
    assert "retry-after" not in response.headers
    return body


@pytest.fixture
def missing_db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "missing.db"
    monkeypatch.setenv("REGISTRY_DB_PATH", str(path))
    return path


@pytest.mark.parametrize(("method", "path", "body"), REQUESTS)
def test_missing_database_is_503(missing_db, method, path, body):
    with TestClient(app) as client:
        response = client.request(method, path, json=body)
    body = assert_unavailable(response)
    assert "missing.db" not in response.text
    assert not missing_db.exists()


def test_health_does_not_need_the_database(missing_db):
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_corrupt_database_is_503(tmp_path: Path, monkeypatch):
    path = tmp_path / "registry.db"
    path.write_bytes(b"this is not a sqlite database " * 200)
    monkeypatch.setenv("REGISTRY_DB_PATH", str(path))
    with TestClient(app) as client:
        response = client.get("/v1/farms")
    assert_unavailable(response)
    assert "not a database" not in response.text


def test_locked_database_is_503(client, db_file, monkeypatch):
    monkeypatch.setattr(db, "BUSY_TIMEOUT_SECONDS", 0.05)
    holder = sqlite3.connect(db_file, isolation_level=None)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        response = client.post("/v1/farms", json={"name": "Blocked farm"})
    finally:
        holder.rollback()
        holder.close()
    assert_unavailable(response)
    assert "locked" not in response.text
    assert [farm["name"] for farm in client.get("/v1/farms").json()] == [
        "Demo cooperative",
        "East farm",
    ]


def test_unavailable_is_logged_for_operations(missing_db, caplog):
    with caplog.at_level(logging.WARNING, logger="errors"):
        with TestClient(app) as client:
            client.get("/v1/farms")
    assert "SQLITE_CANTOPEN" in caplog.text


def test_missing_table_is_a_bug_not_503(server, db_file):
    conn = sqlite3.connect(db_file)
    conn.execute("ALTER TABLE plots RENAME TO plots_renamed")
    conn.commit()
    conn.close()
    response = server.get("/v1/plots")
    assert_internal_error(response)
    assert "plots" not in response.text
    assert "no such table" not in response.text


def test_unexpected_exception_is_500_without_leaking(server, monkeypatch, caplog):
    def explode(*args, **kwargs):
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(farms, "_get_farm", explode)
    with caplog.at_level(logging.ERROR, logger="errors"):
        response = server.get(f"/v1/farms/{DEMO_COOPERATIVE}")
    assert_internal_error(response)
    assert "secret-internal-detail" not in response.text
    assert "RuntimeError" not in response.text
    # The full exception is kept on the server side.
    assert "secret-internal-detail" in caplog.text
    assert "Traceback" in caplog.text


@pytest.mark.parametrize(
    ("errorname", "unavailable"),
    [
        ("SQLITE_CANTOPEN", True),
        ("SQLITE_BUSY", True),
        ("SQLITE_BUSY_SNAPSHOT", True),
        ("SQLITE_LOCKED", True),
        ("SQLITE_IOERR", True),
        ("SQLITE_IOERR_SHORT_READ", True),
        ("SQLITE_NOTADB", True),
        ("SQLITE_CORRUPT", True),
        ("SQLITE_FULL", True),
        ("SQLITE_READONLY", True),
        ("SQLITE_ERROR", False),
        ("SQLITE_CONSTRAINT_UNIQUE", False),
        ("SQLITE_MISUSE", False),
        (None, False),
    ],
)
def test_classification_by_error_code(errorname, unavailable):
    exc = sqlite3.OperationalError("message text is ignored: database is locked")
    exc.sqlite_errorname = errorname
    assert db.is_unavailable(exc) is unavailable
