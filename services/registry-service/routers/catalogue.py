import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from db import get_db
from errors import not_found
from models import Crop, Emitter, Soil

# Read-only (FR-1.2): only GET routes, so any other method gets 405 from the router.
router = APIRouter(prefix="/v1", tags=["catalogue"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]


@router.get("/crops", response_model=list[Crop])
def list_crops(conn: Db) -> list[Crop]:
    rows = conn.execute("SELECT id, name FROM crops ORDER BY rowid").fetchall()
    return [Crop(**row) for row in rows]


@router.get("/crops/{crop_id}", response_model=Crop)
def get_crop(crop_id: str, conn: Db) -> Crop:
    row = conn.execute("SELECT id, name FROM crops WHERE id = ?", (crop_id,)).fetchone()
    if row is None:
        raise not_found("Crop not found")
    return Crop(**row)


@router.get("/soils", response_model=list[Soil])
def list_soils(conn: Db) -> list[Soil]:
    rows = conn.execute(
        "SELECT id, name, available_water_mm_per_m FROM soils ORDER BY rowid"
    ).fetchall()
    return [Soil(**row) for row in rows]


@router.get("/soils/{soil_id}", response_model=Soil)
def get_soil(soil_id: str, conn: Db) -> Soil:
    row = conn.execute(
        "SELECT id, name, available_water_mm_per_m FROM soils WHERE id = ?", (soil_id,)
    ).fetchone()
    if row is None:
        raise not_found("Soil not found")
    return Soil(**row)


@router.get("/emitters", response_model=list[Emitter])
def list_emitters(conn: Db) -> list[Emitter]:
    rows = conn.execute("SELECT id, name, flow_lph FROM emitters ORDER BY rowid").fetchall()
    return [Emitter(**row) for row in rows]


@router.get("/emitters/{emitter_id}", response_model=Emitter)
def get_emitter(emitter_id: str, conn: Db) -> Emitter:
    row = conn.execute(
        "SELECT id, name, flow_lph FROM emitters WHERE id = ?", (emitter_id,)
    ).fetchone()
    if row is None:
        raise not_found("Emitter not found")
    return Emitter(**row)
