import hashlib
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from config import get_settings
from db import DEFAULT_DB_PATH
from main import app

SEED_SCRIPT = Path(__file__).resolve().parent.parent / "seed_registry.sh"


def _fingerprint(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@pytest.fixture(scope="session", autouse=True)
def real_db_untouched():
    before = _fingerprint(DEFAULT_DB_PATH)
    yield
    assert _fingerprint(DEFAULT_DB_PATH) == before, "tests modified the real registry.db"


@pytest.fixture(autouse=True)
def force_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A developer's .env may point at PostgreSQL; tests must never use it.
    monkeypatch.setenv("DATABASE_URL", sqlite_url(tmp_path / "no-database.db"))
    assert get_settings().database_url.startswith("sqlite"), "tests must run on SQLite"


@pytest.fixture
def db_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "registry.db"
    subprocess.run(["bash", str(SEED_SCRIPT), str(path)], check=True, capture_output=True)
    monkeypatch.setenv("DATABASE_URL", sqlite_url(path))
    return path


@pytest.fixture
def client(db_file: Path) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sql_log(client: TestClient) -> list[tuple[str, tuple]]:
    """Every (statement, parameters) sent to the database during the test, as the driver
    gets them: SQLite uses `?` placeholders and a tuple of values."""
    statements: list[tuple[str, tuple]] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append((statement, tuple(parameters)))

    engine = client.app.state.engine
    event.listen(engine, "before_cursor_execute", record)
    yield statements
    event.remove(engine, "before_cursor_execute", record)


def updates(statements: list[tuple[str, tuple]]) -> list[tuple[str, tuple]]:
    return [(sql, params) for sql, params in statements if sql.lstrip().upper().startswith("UPDATE")]


def assert_problem(response, status: int, code: str) -> dict:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert set(body) == {"type", "title", "status", "detail", "code"}
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert body["code"] == code
    assert body["detail"]
    return body


def sqlite_url(path: Path) -> str:
    return f"sqlite:///file:{path}?mode=rw&uri=true"
