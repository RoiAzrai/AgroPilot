import sqlite3
from pathlib import Path

import pytest

import db


def test_fixture_points_at_fresh_seeded_copy(db_file: Path):
    assert db.db_path() == db_file
    assert db_file != db.DEFAULT_DB_PATH
    conn = db.connect()
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("crops", "soils", "emitters", "farms", "plots")
    }
    conn.close()
    assert counts == {"crops": 2, "soils": 3, "emitters": 4, "farms": 2, "plots": 4}


def test_connect_enables_foreign_keys(db_file: Path):
    conn = db.connect()
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("DELETE FROM farms")
    conn.close()


def test_connect_returns_rows_by_column_name(db_file: Path):
    conn = db.connect()
    row = conn.execute("SELECT id, name FROM crops WHERE id = ?", ("tomato",)).fetchone()
    conn.close()
    assert row["name"] == "Tomato"


def test_connect_does_not_create_a_missing_file(tmp_path: Path, monkeypatch):
    missing = tmp_path / "missing.db"
    monkeypatch.setenv("REGISTRY_DB_PATH", str(missing))
    with pytest.raises(sqlite3.OperationalError):
        db.connect()
    assert not missing.exists()


def test_get_db_closes_the_connection(db_file: Path):
    dependency = db.get_db()
    conn = next(dependency)
    with pytest.raises(StopIteration):
        next(dependency)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
