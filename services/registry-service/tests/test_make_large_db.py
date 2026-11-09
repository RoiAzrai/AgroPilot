import random
import sqlite3
import subprocess
from datetime import date

import pytest

from db import DEFAULT_DB_PATH
from models import PlotCreate
from perf.make_large_db import (
    MAX_PLOTS_PER_FARM,
    PLOT_COLUMNS,
    REFERENCE_DATE,
    SEED_SCRIPT,
    build,
    main,
    plots_per_farm,
)


def dump(path):
    conn = sqlite3.connect(path)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def query(path, sql):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(sql)]
    finally:
        conn.close()


@pytest.fixture(scope="module")
def large(tmp_path_factory):
    """The 10,000-plot database (judgment log 21-22), built once for this module."""
    path = tmp_path_factory.mktemp("large") / "large.db"
    return path, build(path, farms=750, plots=10_000)


def test_default_is_2000_plots_on_150_farms(tmp_path):
    summary = build(tmp_path / "default.db")
    assert summary["rows"] == {"farms": 150, "plots": 2_000, "crops": 2, "soils": 3, "emitters": 4}
    assert summary["plots_per_farm"]["farms_5_to_15"] > 150 / 2


@pytest.fixture(scope="module")
def seed_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("seed") / "seed.db"
    subprocess.run(["bash", str(SEED_SCRIPT), str(path)], check=True, capture_output=True)
    return path


def test_counts_are_exact(large):
    path, summary = large
    assert summary["rows"] == {"farms": 750, "plots": 10_000, "crops": 2, "soils": 3, "emitters": 4}
    assert query(path, "SELECT COUNT(*) AS n FROM plots")[0]["n"] == 10_000


def test_seed_rows_and_catalogue_are_unchanged(large, seed_db):
    path, _ = large
    for table in ("crops", "soils", "emitters"):
        assert query(path, f"SELECT * FROM {table} ORDER BY id") == query(
            seed_db, f"SELECT * FROM {table} ORDER BY id"
        )
    seed_plots = query(seed_db, "SELECT * FROM plots ORDER BY id")
    ids = ", ".join(f"'{p['id']}'" for p in seed_plots)
    assert query(path, f"SELECT * FROM plots WHERE id IN ({ids}) ORDER BY id") == seed_plots


def test_every_plot_passes_plot_create(large):
    path, _ = large
    for plot in query(path, f"SELECT {', '.join(PLOT_COLUMNS)} FROM plots"):
        PlotCreate.model_validate({k: v for k, v in plot.items() if k != "id"})


def test_names_are_unique_per_farm(large):
    path, _ = large
    duplicates = query(
        path, "SELECT farm_id, name, COUNT(*) AS n FROM plots GROUP BY farm_id, name HAVING n > 1"
    )
    assert duplicates == []


def test_values_stay_in_the_documented_ranges(large):
    path, summary = large
    generated = query(path, "SELECT * FROM plots WHERE name LIKE 'Block %' OR name LIKE 'Greenhouse %'")
    assert len(generated) == 10_000 - 4
    for plot in generated:
        assert 29.5 < plot["lat"] < 33.3 and 34.2 < plot["lon"] < 35.9
        assert 1.0 <= plot["row_spacing_m"] <= 2.0
        assert 0.2 <= plot["emitter_spacing_m"] <= 0.5
        planted = date.fromisoformat(plot["planting_date"])
        assert 0 <= (REFERENCE_DATE - planted).days < 365
        if plot["name"].startswith("Greenhouse"):
            assert 400 <= plot["area_m2"] <= 2000
        else:
            assert 2000 <= plot["area_m2"] <= 30000
    per_farm = summary["plots_per_farm"]
    assert per_farm["min"] >= 1 and per_farm["max"] <= MAX_PLOTS_PER_FARM
    assert per_farm["farms_5_to_15"] > 750 / 2


def test_same_seed_gives_an_identical_database(tmp_path):
    build(tmp_path / "a.db", seed=3, farms=40, plots=500)
    build(tmp_path / "b.db", seed=3, farms=40, plots=500)
    build(tmp_path / "c.db", seed=4, farms=40, plots=500)
    assert dump(tmp_path / "a.db") == dump(tmp_path / "b.db")
    assert dump(tmp_path / "a.db") != dump(tmp_path / "c.db")


@pytest.mark.parametrize(("farms", "total"), [(10, 10), (10, 2000), (748, 9996), (5, 37)])
def test_plots_per_farm_sum_is_exact_and_bounded(farms, total):
    counts = plots_per_farm(random.Random(1), farms, total)
    assert len(counts) == farms
    assert sum(counts) == total
    assert all(1 <= c <= MAX_PLOTS_PER_FARM for c in counts)


def test_refuses_an_existing_file_and_the_service_database(tmp_path):
    existing = tmp_path / "x.db"
    existing.write_text("keep me")
    with pytest.raises(ValueError, match="already exists"):
        build(existing, farms=10, plots=50)
    assert existing.read_text() == "keep me"
    with pytest.raises(ValueError, match="refusing"):
        build(DEFAULT_DB_PATH, farms=10, plots=50)


def test_main_prints_the_summary(tmp_path, capsys):
    assert main(["--out", str(tmp_path / "m.db"), "--farms", "20", "--plots", "200"]) == 0
    out = capsys.readouterr().out
    assert "Rows: farms 20, plots 200, crops 2, soils 3, emitters 4" in out
    assert "Plots per farm: min" in out
    assert "GET /v1/plots body (approx.)" in out
