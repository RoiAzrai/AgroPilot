"""Build a large, realistic COPY of the registry database for the scale experiment.

It runs seed_registry.sh into the output path (the 2 seed farms, 4 plots and the
catalogue stay as they are), then adds generated farms and plots. Catalogue tables
are not changed. Every generated plot is validated with the service's own
PlotCreate model (FR-1.3) before it is inserted, all in one transaction. The same
--seed always gives the same database.

The plot values are modelling assumptions for a load test, not agronomic fact;
perf/README.md lists them.

Usage, from services/registry-service:
    uv run python perf/make_large_db.py --out perf/results/large-registry.db
    # the 10,000-plot database of judgment log 21-22:
    uv run python perf/make_large_db.py --out perf/results/x.db --plots 10000 --farms 750
"""

import argparse
import json
import math
import random
import sqlite3
import statistics
import subprocess
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_DIR))  # so that `models` and `db` import when run as a script

from db import DEFAULT_DB_PATH  # noqa: E402
from models import PlotCreate  # noqa: E402

SEED_SCRIPT = SERVICE_DIR / "seed_registry.sh"

# Fixed, so the database is reproducible; planting dates fall in the 365 days before it.
REFERENCE_DATE = date(2026, 11, 1)

# Farm centres: a box roughly around Israel. Plots: within ~2 km of their centre.
LAT_RANGE = (29.6, 33.2)
LON_RANGE = (34.3, 35.8)
PLOT_RADIUS_M = 2000
METERS_PER_DEGREE_LAT = 111_320

# Plots per farm: lognormal (median about 9 before scaling), clipped to [1, 200].
PLOTS_PER_FARM_MU = math.log(9)
PLOTS_PER_FARM_SIGMA = 0.7
MIN_PLOTS_PER_FARM = 1
MAX_PLOTS_PER_FARM = 200

GREENHOUSE_SHARE = 0.3
GREENHOUSE_AREA_M2 = (400, 2_000)
OPEN_FIELD_AREA_M2 = (2_000, 30_000)
ROW_SPACING_M = (1.0, 2.0)
EMITTER_SPACING_M = (0.2, 0.5)
CROP_WEIGHTS = {"tomato": 1, "bell-pepper": 1}
SOIL_WEIGHTS = {"loam": 5, "sand": 3, "clay-loam": 2}
EMITTER_WEIGHTS = {"dripnet-pc-1.0": 4, "dripnet-pc-1.6": 3, "dripnet-pc-0.6": 2, "dripnet-pc-2.0": 1}

PLOT_COLUMNS = (
    "id", "farm_id", "name", "area_m2", "crop_id", "planting_date", "soil_id",
    "row_spacing_m", "emitter_spacing_m", "emitter_id", "lat", "lon",
)
CATALOGUE_TABLES = ("crops", "soils", "emitters")
TABLES = ("farms", "plots", *CATALOGUE_TABLES)


def new_uuid(rng: random.Random) -> str:
    """A version-4 UUID drawn from rng (not uuid4(), which is not reproducible)."""
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def weighted(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def plots_per_farm(rng: random.Random, farms: int, total: int) -> list[int]:
    """Lognormal counts, scaled so they sum to exactly `total`, each in [1, 200]."""
    lo, hi = MIN_PLOTS_PER_FARM, MAX_PLOTS_PER_FARM
    if not lo * farms <= total <= hi * farms:
        raise ValueError(f"{total} plots cannot be split over {farms} farms with {lo}-{hi} each")
    raw = [rng.lognormvariate(PLOTS_PER_FARM_MU, PLOTS_PER_FARM_SIGMA) for _ in range(farms)]
    scale = total / sum(raw)
    counts = [min(hi, max(lo, round(x * scale))) for x in raw]
    # Rounding and clipping leave a small remainder: move it one plot at a time.
    while (gap := total - sum(counts)) != 0:
        step = 1 if gap > 0 else -1
        candidates = [i for i, c in enumerate(counts) if lo <= c + step <= hi]
        counts[rng.choice(candidates)] += step
    return counts


def farm_centre(rng: random.Random) -> tuple[float, float]:
    return rng.uniform(*LAT_RANGE), rng.uniform(*LON_RANGE)


def near(rng: random.Random, lat: float, lon: float) -> tuple[float, float]:
    """A point uniformly inside a circle of PLOT_RADIUS_M around (lat, lon)."""
    distance = PLOT_RADIUS_M * math.sqrt(rng.random())
    bearing = rng.uniform(0, 2 * math.pi)
    d_lat = distance * math.cos(bearing) / METERS_PER_DEGREE_LAT
    d_lon = distance * math.sin(bearing) / (METERS_PER_DEGREE_LAT * math.cos(math.radians(lat)))
    return round(lat + d_lat, 6), round(lon + d_lon, 6)


def make_plot(rng: random.Random, farm_id: str, index: int, centre: tuple[float, float]) -> dict:
    """One plot's input, as a client would send it. Its name is unique within the farm."""
    greenhouse = rng.random() < GREENHOUSE_SHARE
    lat, lon = near(rng, *centre)
    return {
        "farm_id": farm_id,
        "name": f"{'Greenhouse' if greenhouse else 'Block'} {index:03d}",
        "area_m2": round(rng.uniform(*(GREENHOUSE_AREA_M2 if greenhouse else OPEN_FIELD_AREA_M2)), 1),
        "crop_id": weighted(rng, CROP_WEIGHTS),
        "planting_date": (REFERENCE_DATE - timedelta(days=rng.randrange(365))).isoformat(),
        "soil_id": weighted(rng, SOIL_WEIGHTS),
        "row_spacing_m": round(rng.uniform(*ROW_SPACING_M), 2),
        "emitter_spacing_m": round(rng.uniform(*EMITTER_SPACING_M), 2),
        "emitter_id": weighted(rng, EMITTER_WEIGHTS),
        "lat": lat,
        "lon": lon,
    }


def generate(seed: int, farms: int, plots: int, existing_farms: int, existing_plots: int):
    """(farm rows, validated plot rows) to add on top of the seed data."""
    new_farms, new_plots = farms - existing_farms, plots - existing_plots
    if new_farms < 1 or new_plots < 0:
        raise ValueError(
            f"--farms/--plots must exceed the seed data ({existing_farms} farms, "
            f"{existing_plots} plots)"
        )
    rng = random.Random(seed)
    counts = plots_per_farm(rng, new_farms, new_plots)
    farm_rows, plot_rows = [], []
    for number, count in enumerate(counts, start=1):
        farm_id = new_uuid(rng)
        farm_rows.append((farm_id, f"Farm {number:04d}"))
        centre = farm_centre(rng)
        for index in range(1, count + 1):
            plot = PlotCreate.model_validate(make_plot(rng, farm_id, index, centre))
            row = plot.model_dump()
            row["planting_date"] = row["planting_date"].isoformat()
            plot_rows.append((new_uuid(rng), *(row[c] for c in PLOT_COLUMNS[1:])))
    return farm_rows, plot_rows


def count_rows(conn: sqlite3.Connection) -> dict[str, int]:
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def build(out: Path, seed: int = 1, farms: int = 150, plots: int = 2_000) -> dict:
    """Write the database to `out` (which must not exist) and return its summary."""
    out = Path(out)
    if out.resolve() == DEFAULT_DB_PATH.resolve():
        raise ValueError(f"refusing to write the service's own database {DEFAULT_DB_PATH}")
    if out.exists():
        raise ValueError(f"{out} already exists; choose a new path")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["bash", str(SEED_SCRIPT), str(out)], check=True, capture_output=True)

    conn = sqlite3.connect(out)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        before = count_rows(conn)
        farm_rows, plot_rows = generate(seed, farms, plots, before["farms"], before["plots"])
        with conn:  # one transaction
            conn.executemany("INSERT INTO farms (id, name) VALUES (?, ?)", farm_rows)
            conn.executemany(
                f"INSERT INTO plots ({', '.join(PLOT_COLUMNS)}) "
                f"VALUES ({', '.join('?' * len(PLOT_COLUMNS))})",
                plot_rows,
            )
        rows = count_rows(conn)
        per_farm = [n for (n,) in conn.execute(
            "SELECT COUNT(p.id) FROM farms f LEFT JOIN plots p ON p.farm_id = f.id GROUP BY f.id"
        )]
        conn.row_factory = sqlite3.Row
        plots_list = [dict(r) for r in conn.execute(f"SELECT {', '.join(PLOT_COLUMNS)} FROM plots")]
    finally:
        conn.close()

    ordered = sorted(per_farm)
    return {
        "path": str(out),
        "seed": seed,
        "reference_date": REFERENCE_DATE.isoformat(),
        "rows": rows,
        "plots_per_farm": {
            "min": ordered[0],
            "median": statistics.median(ordered),
            "p90": ordered[max(1, math.ceil(0.9 * len(ordered))) - 1],
            "max": ordered[-1],
            "farms_5_to_15": sum(5 <= n <= 15 for n in ordered),
        },
        "file_bytes": out.stat().st_size,
        # Compact JSON, as the service sends it; approximate (float formatting may differ).
        "plots_list_json_bytes": len(json.dumps(plots_list, separators=(",", ":")).encode()),
    }


def format_summary(summary: dict) -> str:
    rows, per_farm = summary["rows"], summary["plots_per_farm"]
    farms = rows["farms"]
    return "\n".join([
        f"Wrote {summary['path']} (seed {summary['seed']}, reference date "
        f"{summary['reference_date']})",
        "Rows: " + ", ".join(f"{table} {n}" for table, n in rows.items()),
        f"Plots per farm: min {per_farm['min']}, median {per_farm['median']:g}, "
        f"p90 {per_farm['p90']}, max {per_farm['max']}; farms with 5-15 plots: "
        f"{per_farm['farms_5_to_15']} of {farms} ({per_farm['farms_5_to_15'] / farms:.0%})",
        f"Database file: {summary['file_bytes'] / 1024 / 1024:.2f} MB",
        f"GET /v1/plots body (approx.): {summary['plots_list_json_bytes'] / 1024 / 1024:.2f} MB",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="new database file to write")
    parser.add_argument("--plots", type=int, default=2_000, help="total plots, seed plots included")
    parser.add_argument("--farms", type=int, default=150, help="total farms, seed farms included")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        summary = build(args.out, args.seed, args.farms, args.plots)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(format_summary(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
