import hashlib
import subprocess
from pathlib import Path

import boto3
import boto3.session
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


@pytest.fixture(autouse=True)
def aws_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Dummy settings for the required keys, and no way to find real credentials:
    # no ~/.aws files, no instance metadata.
    monkeypatch.setenv("AWS_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def no_real_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test that reaches real boto3 fails instead of calling AWS. Photo tests replace
    routers.plots._s3_client with a fake."""

    def blocked(*args, **kwargs):
        raise AssertionError("tests must not create a real boto3 client")

    monkeypatch.setattr(boto3, "client", blocked)
    monkeypatch.setattr(boto3.session.Session, "client", blocked)


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
