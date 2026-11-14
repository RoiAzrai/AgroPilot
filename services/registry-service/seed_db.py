"""Create the registry tables and load the seed rows in the database named by DATABASE_URL.

Usage, from services/registry-service:
    uv run python seed_db.py            # create tables + load seed rows
    uv run python seed_db.py --reset    # drop and rebuild the five tables
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    Double,
    Engine,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
)
from sqlalchemy.engine import URL, make_url
from sqlalchemy.types import REAL

from config import get_settings

TABLES: tuple[str, ...] = ("crops", "soils", "emitters", "farms", "plots")

SEED_ROWS: dict[str, list[dict[str, Any]]] = {
    "crops": [
        {"id": "tomato", "name": "Tomato"},
        {"id": "bell-pepper", "name": "Bell pepper"},
    ],
    "soils": [
        {"id": "sand", "name": "Sand", "available_water_mm_per_m": 83},
        {"id": "loam", "name": "Loam", "available_water_mm_per_m": 175},
        {"id": "clay-loam", "name": "Clay loam", "available_water_mm_per_m": 200},
    ],
    "emitters": [
        {"id": "dripnet-pc-0.6", "name": "DripNet PC", "flow_lph": 0.6},
        {"id": "dripnet-pc-1.0", "name": "DripNet PC", "flow_lph": 1.0},
        {"id": "dripnet-pc-1.6", "name": "DripNet PC", "flow_lph": 1.6},
        {"id": "dripnet-pc-2.0", "name": "DripNet PC", "flow_lph": 2.0},
    ],
    "farms": [
        {"id": "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001", "name": "Demo cooperative"},
        {"id": "a9c1e4b2-6f70-4d8e-a144-3f8b5c904004", "name": "East farm"},
    ],
    "plots": [
        {
            "id": "c8f3d1b0-4d2e-5a1b-8b22-1d6e3f702002",
            "farm_id": "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001",
            "name": "North block", "area_m2": 1000, "crop_id": "tomato",
            "planting_date": "2026-03-01", "soil_id": "loam",
            "row_spacing_m": 1.5, "emitter_spacing_m": 0.4,
            "emitter_id": "dripnet-pc-1.0", "lat": 31.25, "lon": 34.79,
        },
        {
            "id": "d9a4e2c1-5e3f-4b6a-9c33-2e7f4a803003",
            "farm_id": "b7e2c0a0-3c1d-4f0a-9a11-0c5d2e6f1001",
            "name": "East block", "area_m2": 800, "crop_id": "bell-pepper",
            "planting_date": "2026-04-12", "soil_id": "clay-loam",
            "row_spacing_m": 1.5, "emitter_spacing_m": 0.4,
            "emitter_id": "dripnet-pc-1.6", "lat": 31.26, "lon": 34.80,
        },
        {
            "id": "e0b5f3d2-6f40-4c7b-8d44-3f8a5b914004",
            "farm_id": "a9c1e4b2-6f70-4d8e-a144-3f8b5c904004",
            "name": "West block", "area_m2": 1500, "crop_id": "tomato",
            "planting_date": "2026-02-15", "soil_id": "sand",
            "row_spacing_m": 1.5, "emitter_spacing_m": 0.4,
            "emitter_id": "dripnet-pc-0.6", "lat": 31.40, "lon": 34.60,
        },
        {
            "id": "f1c6a4e3-7051-4d8c-9e55-4a9b6c025005",
            "farm_id": "a9c1e4b2-6f70-4d8e-a144-3f8b5c904004",
            "name": "Greenhouse", "area_m2": 400, "crop_id": "bell-pepper",
            "planting_date": "2026-05-01", "soil_id": "loam",
            "row_spacing_m": 1.2, "emitter_spacing_m": 0.3,
            "emitter_id": "dripnet-pc-2.0", "lat": 31.41, "lon": 34.61,
        },
    ],
}


class TablesExistError(Exception):
    pass


def build_metadata(dialect_name: str) -> MetaData:
    postgres = dialect_name == "postgresql"
    real = Double() if postgres else REAL()
    metadata = MetaData()

    def table(name: str, *items: Any) -> None:
        extra = [Column("rowid", BigInteger, Identity(always=True), nullable=False)] if postgres else []
        Table(name, metadata, *items, *extra)

    def text(name: str, *constraints: Any) -> Column:
        return Column(name, Text, *constraints, nullable=False)

    table("farms", Column("id", Text, primary_key=True), text("name"))
    table("crops", Column("id", Text, primary_key=True), text("name"))
    table(
        "soils",
        Column("id", Text, primary_key=True),
        text("name"),
        Column("available_water_mm_per_m", Integer, nullable=False),
    )
    table(
        "emitters",
        Column("id", Text, primary_key=True),
        text("name"),
        Column("flow_lph", real, nullable=False),
    )
    table(
        "plots",
        Column("id", Text, primary_key=True),
        text("farm_id", ForeignKey("farms.id")),
        text("name"),
        Column("area_m2", real, nullable=False),
        text("crop_id", ForeignKey("crops.id")),
        text("planting_date"),
        text("soil_id", ForeignKey("soils.id")),
        Column("row_spacing_m", real, nullable=False),
        Column("emitter_spacing_m", real, nullable=False),
        text("emitter_id", ForeignKey("emitters.id")),
        Column("lat", real, nullable=False),
        Column("lon", real, nullable=False),
        UniqueConstraint("farm_id", "name", name="plots_farm_id_name_key"),
    )
    return metadata


def create_and_seed(engine: Engine, *, reset: bool) -> None:
    existing = [t for t in TABLES if t in inspect(engine).get_table_names()]
    if existing and not reset:
        raise TablesExistError(f"Tables already exist: {', '.join(existing)}")
    metadata = build_metadata(engine.dialect.name)
    with engine.begin() as conn:
        for name in reversed(TABLES):
            if name in existing:
                conn.exec_driver_sql(f"DROP TABLE {name}")
        metadata.create_all(conn)
        for name in TABLES:
            conn.execute(metadata.tables[name].insert(), SEED_ROWS[name])


def describe_target(url: URL) -> str:
    if url.get_backend_name() == "sqlite":
        database = url.database or ""
        if database.startswith("file:"):
            database = database[len("file:"):]
        return f"sqlite file {Path(database).resolve()}"
    return (
        f"{url.get_backend_name()} database '{url.database}' "
        f"on {url.host}:{url.port} as {url.username}"
    )


def seed_url(database_url: str) -> str:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or url.query.get("mode") != "rw":
        return database_url
    return url.update_query_dict({"mode": "rwc"}).render_as_string(hide_password=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and seed the registry tables.")
    parser.add_argument("--reset", action="store_true", help="drop and rebuild the tables")
    args = parser.parse_args(argv)

    database_url = get_settings().database_url
    target = describe_target(make_url(database_url))
    if args.reset:
        print(f"Resetting {target}")
    engine = create_engine(seed_url(database_url))
    try:
        create_and_seed(engine, reset=args.reset)
    except TablesExistError as exc:
        print(f"{exc}; use --reset to rebuild", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"Created and seeded {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
