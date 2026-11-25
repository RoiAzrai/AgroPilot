import runpy
import sqlite3
import subprocess
import sys
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


def _renamed_kept(path: Path) -> bool:
    con = sqlite3.connect(path)
    try:
        return ("Renamed",) in con.execute("SELECT name FROM farms").fetchall()
    finally:
        con.close()


def _terminal(monkeypatch, answer):
    """stdin is a terminal; `answer` is what the person types (an exception is raised)."""
    asked = []

    def fake_input(prompt):
        asked.append(prompt)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", fake_input)
    return asked


def test_reset_with_yes_rebuilds_without_asking(target, tmp_path, monkeypatch, capsys):
    assert seed_db.main([]) == 0
    _rename_farm(target)
    capsys.readouterr()
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("must not ask"))
    assert seed_db.main(["--reset", "--yes"]) == 0
    assert capsys.readouterr().out.startswith("Resetting sqlite file")
    assert _dump(target) == _reference_rows(tmp_path)


def test_reset_confirmed_by_typing_the_name(target, tmp_path, monkeypatch, capsys):
    assert seed_db.main([]) == 0
    _rename_farm(target)
    capsys.readouterr()
    asked = _terminal(monkeypatch, " new.db \n")
    assert seed_db.main(["--reset"]) == 0
    assert asked == ["Type the database name (new.db) to delete all registry data: "]
    out = capsys.readouterr().out
    assert out.startswith(f"Resetting sqlite file {target.resolve()}")
    assert _dump(target) == _reference_rows(tmp_path)


@pytest.mark.parametrize(
    "answer", ["registry.db", "", "y", EOFError()], ids=["wrong-name", "empty", "y", "ctrl-d"]
)
def test_reset_refused_without_the_right_name(target, monkeypatch, capsys, answer):
    assert seed_db.main([]) == 0
    _rename_farm(target)
    capsys.readouterr()
    _terminal(monkeypatch, answer)
    assert seed_db.main(["--reset"]) == 1
    assert "Not confirmed; nothing was changed." in capsys.readouterr().err
    assert _renamed_kept(target)


def test_reset_without_terminal_or_yes_is_refused(target, monkeypatch, capsys):
    assert seed_db.main([]) == 0
    _rename_farm(target)
    capsys.readouterr()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("must not ask"))
    assert seed_db.main(["--reset"]) == 1
    assert "pass --yes" in capsys.readouterr().err
    assert _renamed_kept(target)


def test_without_reset_nothing_is_asked(target, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("must not ask"))
    assert seed_db.main([]) == 0
    assert capsys.readouterr().out.startswith("Created and seeded sqlite file")


def test_confirm_name_of_a_postgres_url_is_the_driver_dbname():
    url = make_url("postgresql+psycopg://alice:pw@db.example:5432/registry?dbname=registry_perf")
    assert seed_db.database_name(url) == "registry_perf"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql+psycopg://alice:pw@db.example:5433/registry?dbname=registry_perf",
            "postgresql database 'registry_perf' on db.example:5433 as alice",
        ),
        (
            "postgresql+psycopg://alice:pw@db.example:5433/registry?host=other.example",
            "postgresql database 'registry' on other.example:5433 as alice",
        ),
        (
            "postgresql+psycopg:///?host=/var/run/postgresql&dbname=registry_perf&user=bob",
            "postgresql database 'registry_perf' on /var/run/postgresql:None as bob",
        ),
    ],
    ids=["query-dbname", "query-host", "query-only"],
)
def test_describe_target_shows_what_the_driver_uses(url, expected):
    assert seed_db.describe_target(make_url(url)) == expected


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


def test_describe_target_of_plain_sqlite_path(tmp_path):
    path = tmp_path / "plain.db"
    text = seed_db.describe_target(make_url(f"sqlite:///{path}"))
    assert text == f"sqlite file {path.resolve()}"


def test_running_the_module_seeds_the_database(tmp_path, monkeypatch, capsys):
    path = tmp_path / "from-main.db"
    monkeypatch.setenv("DATABASE_URL", sqlite_url(path).replace("mode=rw", "mode=rwc"))
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setattr(sys, "argv", ["seed_db.py"])
    with pytest.raises(SystemExit) as exited:
        runpy.run_module("seed_db", run_name="__main__")
    assert exited.value.code == 0
    assert capsys.readouterr().out.startswith("Created and seeded sqlite file")
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM plots").fetchone()[0] == 4
    conn.close()


def test_seed_creates_an_empty_plot_photos_table(target):
    assert seed_db.main([]) == 0
    con = sqlite3.connect(target)
    assert con.execute("SELECT COUNT(*) FROM plot_photos").fetchone()[0] == 0
    con.close()


def test_postgres_plot_photos_cascades_and_has_rowid():
    table = seed_db.build_metadata("postgresql").tables[seed_db.PHOTO_TABLE]
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "REFERENCES plots (id) ON DELETE CASCADE" in ddl
    assert "rowid BIGINT GENERATED ALWAYS AS IDENTITY" in ddl
    assert seed_db.PHOTO_TABLE not in seed_db.TABLES


def test_reset_drops_plot_photos_too(target, tmp_path, capsys):
    assert seed_db.main([]) == 0
    con = sqlite3.connect(target)
    con.execute(
        "INSERT INTO plot_photos (plot_id, key, content_type)"
        " VALUES ('c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002', 'k', 'image/png')"
    )
    con.commit()
    con.close()
    assert seed_db.main(["--reset", "--yes"]) == 0
    con = sqlite3.connect(target)
    assert con.execute("SELECT COUNT(*) FROM plot_photos").fetchone()[0] == 0
    con.close()
    assert _dump(target) == _reference_rows(tmp_path)


def test_reset_of_a_database_from_before_plot_photos(target, tmp_path):
    subprocess.run(["bash", str(SEED_SCRIPT), str(target)], check=True, capture_output=True)
    _rename_farm(target)
    assert seed_db.main(["--reset", "--yes"]) == 0
    assert _dump(target) == _reference_rows(tmp_path)
    con = sqlite3.connect(target)
    assert con.execute("SELECT COUNT(*) FROM plot_photos").fetchone()[0] == 0
    con.close()
