from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from db import get_db
from errors import not_found
from models import Crop, Emitter, Soil

# Read-only (FR-1.2): only GET routes, so any other method gets 405 from the router.
router = APIRouter(prefix="/v1", tags=["catalogue"])

Db = Annotated[Connection, Depends(get_db)]


@router.get("/crops", response_model=list[Crop])
def list_crops(conn: Db) -> list[Crop]:
    rows = conn.execute(text("SELECT id, name FROM crops ORDER BY rowid")).mappings().fetchall()
    return [Crop(**row) for row in rows]


@router.get("/crops/{crop_id}", response_model=Crop)
def get_crop(crop_id: str, conn: Db) -> Crop:
    if "\x00" in crop_id:  # PostgreSQL cannot compare TEXT with NUL
        raise not_found("Crop not found")
    row = conn.execute(
        text("SELECT id, name FROM crops WHERE id = :id"), {"id": crop_id}
    ).mappings().fetchone()
    if row is None:
        raise not_found("Crop not found")
    return Crop(**row)


@router.get("/soils", response_model=list[Soil])
def list_soils(conn: Db) -> list[Soil]:
    rows = conn.execute(
        text("SELECT id, name, available_water_mm_per_m FROM soils ORDER BY rowid")
    ).mappings().fetchall()
    return [Soil(**row) for row in rows]


@router.get("/soils/{soil_id}", response_model=Soil)
def get_soil(soil_id: str, conn: Db) -> Soil:
    if "\x00" in soil_id:  # PostgreSQL cannot compare TEXT with NUL
        raise not_found("Soil not found")
    row = conn.execute(
        text("SELECT id, name, available_water_mm_per_m FROM soils WHERE id = :id"),
        {"id": soil_id},
    ).mappings().fetchone()
    if row is None:
        raise not_found("Soil not found")
    return Soil(**row)


@router.get("/emitters", response_model=list[Emitter])
def list_emitters(conn: Db) -> list[Emitter]:
    rows = conn.execute(
        text("SELECT id, name, flow_lph FROM emitters ORDER BY rowid")
    ).mappings().fetchall()
    return [Emitter(**row) for row in rows]


@router.get("/emitters/{emitter_id}", response_model=Emitter)
def get_emitter(emitter_id: str, conn: Db) -> Emitter:
    if "\x00" in emitter_id:  # PostgreSQL cannot compare TEXT with NUL
        raise not_found("Emitter not found")
    row = conn.execute(
        text("SELECT id, name, flow_lph FROM emitters WHERE id = :id"), {"id": emitter_id}
    ).mappings().fetchone()
    if row is None:
        raise not_found("Emitter not found")
    return Emitter(**row)
