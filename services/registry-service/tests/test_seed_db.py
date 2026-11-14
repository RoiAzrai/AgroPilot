import sqlite3
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateTable

import config
import seed_db
from conftest import SEED_SCRIPT, sqlite_url

TABLES = ("crops", "soils", "emitters", "farms", "plots")


def _reference(tmp_path: Path) -> dict:
    path = tmp_path / "reference.db"
    subprocess.run(["bash", str(SEED_SCRIPT), str(path)], check=True, capture_output=True)
    engine = create_engine(sqlite_url(path))
    insp = inspect(engine)
    ref = {}
    for table in TABLES:
        pk = insp.get_pk_constraint(table)["constrained_columns"]
        ref[table] = {
            "columns": [
                (c["name"], str(c["type"]), c["nullable"] or c["name"] in pk)
                for c in insp.get_columns(table)
            ],
            "pk": pk,
            "fks": sorted(
                (tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]))
                for f in insp.get_foreign_keys(table)
            ),
            "uniques": sorted(
                tuple(u["column_names"]) for u in insp.get_unique_constraints(table)
            ),
        }
    engine.dispose()
    return ref


def _described(dialect_name: str, dialect) -> dict:
    metadata = seed_db.build_metadata(dialect_name)
    out = {}
    for name in TABLES:
        table = metadata.tables[name]
        pk = [c.name for c in table.primary_key.columns]
        out[name] = {
            "columns": [
                (c.name, c.type.compile(dialect=dialect), c.nullable or c.name in pk)
                for c in table.columns
            ],
            "pk": pk,
            "fks": sorted(
                (
                    tuple(e.parent.name for e in fk.elements),
                    fk.referred_table.name,
                    tuple(e.column.name for e in fk.elements),
                )
                for fk in table.foreign_key_constraints
            ),
            "uniques": sorted(
                tuple(c.name for c in u.columns)
                for u in table.constraints
                if u.__class__.__name__ == "UniqueConstraint"
            ),
        }
    return out


def test_schema_matches_seed_script_on_sqlite(tmp_path):
    assert _described("sqlite", sqlite.dialect()) == _reference(tmp_path)


def test_postgres_schema_differs_only_by_rowid(tmp_path):
    ref = _reference(tmp_path)
    for table in ref.values():
        table["columns"] = [
            (n, "DOUBLE PRECISION" if t == "REAL" else t, nl) for n, t, nl in table["columns"]
        ]
    pg = _described("postgresql", postgresql.dialect())
    for name in TABLES:
        extra = [c for c in pg[name]["columns"] if c[0] == "rowid"]
        assert len(extra) == 1
        assert pg[name]["columns"][-1][0] == "rowid"
        pg[name]["columns"] = [c for c in pg[name]["columns"] if c[0] != "rowid"]
    assert pg == ref


def test_postgres_ddl_emits_identity_and_double_precision():
    metadata = seed_db.build_metadata("postgresql")
    ddl = str(CreateTable(metadata.tables["plots"]).compile(dialect=postgresql.dialect()))
    assert "GENERATED ALWAYS AS IDENTITY" in ddl
    assert "DOUBLE PRECISION" in ddl
    assert "CONSTRAINT plots_farm_id_name_key UNIQUE (farm_id, name)" in ddl
    assert "REAL" not in ddl


@pytest.fixture
def target(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "new.db"
    monkeypatch.setenv("DATABASE_URL", sqlite_url(path))
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "missing.env")
    return path


def _dump(path: Path) -> dict:
    con = sqlite3.connect(path)
    try:
        return {t: con.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in TABLES}
    finally:
        con.close()


def _reference_rows(tmp_path: Path) -> dict:
    path = tmp_path / "reference.db"
    subprocess.run(["bash", str(SEED_SCRIPT), str(path)], check=True, capture_output=True)
    return _dump(path)


def _rename_farm(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("UPDATE farms SET name = 'Renamed' WHERE name = 'East farm'")
    con.commit()
    con.close()


def test_seed_rows_match_seed_script(target, tmp_path):
    assert seed_db.main([]) == 0
    rows = _dump(target)
    assert rows == _reference_rows(tmp_path)
    assert sum(len(v) for v in rows.values()) == 15


def test_existing_tables_are_refused(target, capsys):
    assert seed_db.main([]) == 0
    _rename_farm(target)
    capsys.readouterr()
    assert seed_db.main([]) == 1
    assert "--reset" in capsys.readouterr().err
    assert ("Renamed",) in sqlite3.connect(target).execute("SELECT name FROM farms").fetchall()


def test_reset_rebuilds(target, tmp_path, capsys):
    assert seed_db.main([]) == 0
    _rename_farm(target)
    capsys.readouterr()
    assert seed_db.main(["--reset"]) == 0
    assert capsys.readouterr().out.startswith("Resetting sqlite file")
    assert _dump(target) == _reference_rows(tmp_path)


def test_describe_target_never_shows_password():
    url = make_url("postgresql+psycopg://alice:p%40ss%3Aw0rd@db.example:5433/registry_perf")
    text = seed_db.describe_target(url)
    for part in ("registry_perf", "db.example", "5433", "alice"):
        assert part in text
    for part in ("p@ss", "p%40ss", "w0rd"):
        assert part not in text


def test_database_error_is_one_line_without_password(tmp_path, monkeypatch, capsys):
    import psycopg
    import sqlalchemy.exc

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://alice:s3cret@db.example:5432/registry_perf"
    )
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "missing.env")

    def fail(engine, *, reset):
        raise sqlalchemy.exc.OperationalError(
            "SELECT 1", {}, psycopg.OperationalError('password authentication failed for user "alice"')
        )

    monkeypatch.setattr(seed_db, "create_and_seed", fail)
    assert seed_db.main([]) == 1
    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1
    assert "registry_perf" in lines[0]
    assert "password authentication failed" in lines[0]
    assert "s3cret" not in captured.err + captured.out
    assert "Traceback" not in captured.err + captured.out


def test_unopenable_sqlite_file_is_one_line(tmp_path, monkeypatch, capsys):
    path = tmp_path / "no-such-dir" / "x.db"
    monkeypatch.setenv("DATABASE_URL", sqlite_url(path))
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "missing.env")
    assert seed_db.main([]) == 1
    lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("Cannot seed sqlite file")
    assert not path.exists()
