import sqlite3
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Response

from db import get_db
from errors import conflict, not_found
from models import Farm, FarmCreate, FarmUpdate, canonical_uuid, merge

router = APIRouter(prefix="/v1/farms", tags=["farms"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]


def _farm_id(raw: str) -> str:
    farm_id = canonical_uuid(raw)
    if farm_id is None:
        raise not_found("Farm not found")
    return farm_id


def _get_farm(conn: sqlite3.Connection, farm_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT id, name FROM farms WHERE id = ?", (farm_id,)).fetchone()
    if row is None:
        raise not_found("Farm not found")
    return row


@router.post("", status_code=201, response_model=Farm)
def create_farm(body: FarmCreate, conn: Db) -> Farm:
    farm = Farm(id=uuid4(), name=body.name)
    with conn:
        conn.execute("INSERT INTO farms (id, name) VALUES (?, ?)", (str(farm.id), farm.name))
    return farm


@router.get("", response_model=list[Farm])
def list_farms(conn: Db) -> list[Farm]:
    rows = conn.execute("SELECT id, name FROM farms ORDER BY rowid").fetchall()
    return [Farm(**row) for row in rows]


@router.get("/{farm_id}", response_model=Farm)
def get_farm(farm_id: str, conn: Db) -> Farm:
    return Farm(**_get_farm(conn, _farm_id(farm_id)))


@router.patch("/{farm_id}", response_model=Farm)
def update_farm(farm_id: str, body: FarmUpdate, conn: Db) -> Farm:
    farm_id = _farm_id(farm_id)
    updated = merge(FarmCreate, _get_farm(conn, farm_id), body.model_dump(exclude_unset=True))
    with conn:
        changed = conn.execute(
            "UPDATE farms SET name = ? WHERE id = ?", (updated.name, farm_id)
        ).rowcount
    if changed == 0:
        raise not_found("Farm not found")
    return Farm(id=farm_id, name=updated.name)


@router.delete("/{farm_id}", status_code=204, response_class=Response)
def delete_farm(farm_id: str, conn: Db) -> Response:
    farm_id = _farm_id(farm_id)
    try:
        with conn:
            deleted = conn.execute("DELETE FROM farms WHERE id = ?", (farm_id,)).rowcount
    except sqlite3.IntegrityError as exc:
        # The only foreign keys pointing at farms are plots.farm_id.
        if "FOREIGN KEY" not in str(exc):
            raise
        raise conflict("Farm has plots; delete or move them first") from exc
    if deleted == 0:
        raise not_found("Farm not found")
    return Response(status_code=204)
