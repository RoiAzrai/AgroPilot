from typing import Annotated
from uuid import uuid4

import sqlalchemy.exc
from fastapi import APIRouter, Depends, Response
from sqlalchemy import Connection, RowMapping, text

from db import get_db, is_foreign_key_violation
from errors import conflict, not_found
from models import Farm, FarmCreate, FarmUpdate, canonical_uuid, merge

router = APIRouter(prefix="/v1/farms", tags=["farms"])

Db = Annotated[Connection, Depends(get_db)]


def _farm_id(raw: str) -> str:
    farm_id = canonical_uuid(raw)
    if farm_id is None:
        raise not_found("Farm not found")
    return farm_id


def _get_farm(conn: Connection, farm_id: str) -> RowMapping:
    row = conn.execute(
        text("SELECT id, name FROM farms WHERE id = :id"), {"id": farm_id}
    ).mappings().fetchone()
    if row is None:
        raise not_found("Farm not found")
    return row


@router.post("", status_code=201, response_model=Farm)
def create_farm(body: FarmCreate, conn: Db) -> Farm:
    farm = Farm(id=uuid4(), name=body.name)
    conn.execute(
        text("INSERT INTO farms (id, name) VALUES (:id, :name)"),
        {"id": str(farm.id), "name": farm.name},
    )
    conn.commit()
    return farm


@router.get("", response_model=list[Farm])
def list_farms(conn: Db) -> list[Farm]:
    rows = conn.execute(text("SELECT id, name FROM farms ORDER BY rowid")).mappings().fetchall()
    return [Farm(**row) for row in rows]


@router.get("/{farm_id}", response_model=Farm)
def get_farm(farm_id: str, conn: Db) -> Farm:
    return Farm(**_get_farm(conn, _farm_id(farm_id)))


@router.patch("/{farm_id}", response_model=Farm)
def update_farm(farm_id: str, body: FarmUpdate, conn: Db) -> Farm:
    farm_id = _farm_id(farm_id)
    updated = merge(FarmCreate, _get_farm(conn, farm_id), body.model_dump(exclude_unset=True))
    changed = conn.execute(
        text("UPDATE farms SET name = :name WHERE id = :id"),
        {"name": updated.name, "id": farm_id},
    ).rowcount
    conn.commit()
    if changed == 0:
        raise not_found("Farm not found")
    return Farm(id=farm_id, name=updated.name)


@router.delete("/{farm_id}", status_code=204, response_class=Response)
def delete_farm(farm_id: str, conn: Db) -> Response:
    farm_id = _farm_id(farm_id)
    try:
        deleted = conn.execute(
            text("DELETE FROM farms WHERE id = :id"), {"id": farm_id}
        ).rowcount
        conn.commit()
    except sqlalchemy.exc.IntegrityError as exc:
        # The only foreign keys pointing at farms are plots.farm_id.
        if not is_foreign_key_violation(exc.orig):
            raise
        raise conflict("Farm has plots; delete or move them first") from exc
    if deleted == 0:
        raise not_found("Farm not found")
    return Response(status_code=204)
