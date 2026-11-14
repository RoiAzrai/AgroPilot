from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy.exc
from fastapi.testclient import TestClient
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
