from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy.exc
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

import config
import db
from config import get_settings
from conftest import sqlite_url
from main import app


def test_fixture_points_at_fresh_seeded_copy(db_file: Path):
    assert get_settings().database_url == sqlite_url(db_file)
    assert db_file != db.DEFAULT_DB_PATH
    with db.make_engine(get_settings()).connect() as conn:
        counts = {
            table: conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in ("crops", "soils", "emitters", "farms", "plots")
        }
    assert counts == {"crops": 2, "soils": 3, "emitters": 4, "farms": 2, "plots": 4}


def test_connect_enables_foreign_keys(db_file: Path):
    with db.make_engine(get_settings()).connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        with pytest.raises(sqlalchemy.exc.IntegrityError, match="FOREIGN KEY"):
            conn.execute(text("DELETE FROM farms"))


def test_connect_returns_rows_by_column_name(db_file: Path):
    with db.make_engine(get_settings()).connect() as conn:
        row = conn.execute(
            text("SELECT id, name FROM crops WHERE id = :id"), {"id": "tomato"}
        ).mappings().fetchone()
    assert row["name"] == "Tomato"


def test_connect_does_not_create_a_missing_file(tmp_path: Path, monkeypatch):
    missing = tmp_path / "missing.db"
    monkeypatch.setenv("DATABASE_URL", sqlite_url(missing))
    engine = db.make_engine(get_settings())
    with pytest.raises(sqlalchemy.exc.OperationalError):
        engine.connect()
    assert not missing.exists()


def test_get_db_closes_the_connection(db_file: Path):
    engine = db.make_engine(get_settings())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))
    dependency = db.get_db(request)
    conn = next(dependency)
    with pytest.raises(StopIteration):
        next(dependency)
    assert conn.closed is True


def test_force_sqlite_is_active(tmp_path: Path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgresql+psycopg://x@localhost/registry\n")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    assert get_settings().database_url.startswith("sqlite")


def test_startup_fails_without_database_url(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "missing.env")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        with TestClient(app):
            pass


PG_URL = "postgresql+psycopg://u:p@localhost:5432/registry_perf"


def _pg_settings(**overrides) -> config.Settings:
    return config.Settings(database_url=PG_URL, _env_file=None, **overrides)


def test_postgres_engine_options():
    settings = _pg_settings(
        db_busy_timeout_seconds=5, db_pool_timeout_seconds=5, db_connect_timeout_seconds=3
    )
    assert db.engine_kwargs(settings) == {
        "pool_pre_ping": True,
        "pool_timeout": 5,
        "connect_args": {"connect_timeout": 3, "options": "-c lock_timeout=5000"},
    }


def test_postgres_engine_is_created_without_connecting():
    from sqlalchemy.pool import QueuePool

    engine = db.make_engine(_pg_settings())
    try:
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool.timeout() == 5
    finally:
        engine.dispose()


def test_lock_timeout_follows_busy_timeout():
    kwargs = db.engine_kwargs(_pg_settings(db_busy_timeout_seconds=0.25))
    assert kwargs["connect_args"]["options"] == "-c lock_timeout=250"


def test_other_settings_errors_are_not_masked_as_missing_url(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT_SECONDS", "soon")
    with pytest.raises(ValidationError) as caught:
        get_settings()
    assert [err["loc"] for err in caught.value.errors()] == [("db_connect_timeout_seconds",)]


def test_unexpected_exception_is_not_unavailable_and_has_unknown_driver_code():
    error = ValueError("not a driver error")
    assert db.is_unavailable(error) is False
    assert db.driver_code(error) == "unknown"


def test_unsupported_backend_is_rejected():
    settings = config.Settings(database_url="mysql://u:p@localhost/registry", _env_file=None)
    with pytest.raises(ValueError, match="Unsupported database backend: mysql"):
        db.engine_kwargs(settings)
