import hashlib
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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


@pytest.fixture
def db_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "registry.db"
    subprocess.run(["bash", str(SEED_SCRIPT), str(path)], check=True, capture_output=True)
    monkeypatch.setenv("REGISTRY_DB_PATH", str(path))
    return path


@pytest.fixture
def client(db_file: Path) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


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
