from collections.abc import Mapping
from typing import Annotated, Any
from uuid import UUID, uuid4

import sqlalchemy.exc
from fastapi import APIRouter, Depends, Response
from sqlalchemy import Connection, RowMapping, text

from db import get_db, is_foreign_key_violation
from errors import not_found, validation
from models import Plot, PlotCreate, PlotUpdate, canonical_uuid, merge

router = APIRouter(prefix="/v1/plots", tags=["plots"])

Db = Annotated[Connection, Depends(get_db)]

_FIELDS = tuple(PlotCreate.model_fields)
_SELECT = f"SELECT id, {', '.join(_FIELDS)} FROM plots"

# Field -> (table, detail). Table names come only from this mapping, never from input.
_REFERENCES = {
    "farm_id": ("farms", "Unknown farm"),
    "crop_id": ("crops", "Unknown crop"),
    "soil_id": ("soils", "Unknown soil"),
    "emitter_id": ("emitters", "Unknown emitter"),
}


def check_references(conn: Connection, values: Mapping[str, Any]) -> None:
    """Raise 422 for the first referenced id in values that does not exist."""
    for field, (table, detail) in _REFERENCES.items():
        if field not in values:
            continue
        if "\x00" in values[field]:  # PostgreSQL cannot compare TEXT with NUL
            raise validation(detail)
        row = conn.execute(
            text(f"SELECT 1 FROM {table} WHERE id = :id"), {"id": values[field]}
        ).fetchone()
        if row is None:
            raise validation(detail)


def _write(conn: Connection, sql: str, params: dict[str, Any]) -> int:
    try:
        rowcount = conn.execute(text(sql), params).rowcount
        conn.commit()
        return rowcount
    except sqlalchemy.exc.IntegrityError as exc:
        # Safety net: a reference removed between check_references and the write.
        if not is_foreign_key_violation(exc.orig):
            raise
        raise validation("Unknown farm, crop, soil or emitter") from exc


def _plot_id(raw: str) -> str:
    plot_id = canonical_uuid(raw)
    if plot_id is None:
        raise not_found("Plot not found")
    return plot_id


def _get_plot(conn: Connection, plot_id: str) -> RowMapping:
    row = conn.execute(
        text(f"{_SELECT} WHERE id = :id"), {"id": plot_id}
    ).mappings().fetchone()
    if row is None:
        raise not_found("Plot not found")
    return row


@router.post("", status_code=201, response_model=Plot)
def create_plot(body: PlotCreate, conn: Db) -> Plot:
    values = body.model_dump(mode="json")
    check_references(conn, values)
    plot_id = str(uuid4())
    _write(
        conn,
        f"INSERT INTO plots (id, {', '.join(_FIELDS)})"
        f" VALUES (:id, {', '.join(f':{field}' for field in _FIELDS)})",
        {"id": plot_id, **values},
    )
    return Plot(id=plot_id, **values)


@router.get("", response_model=list[Plot])
def list_plots(conn: Db, farm_id: UUID | None = None) -> list[Plot]:
    if farm_id is None:
        rows = conn.execute(text(f"{_SELECT} ORDER BY rowid")).mappings().fetchall()
    else:
        rows = conn.execute(
            text(f"{_SELECT} WHERE farm_id = :farm_id ORDER BY rowid"),
            {"farm_id": str(farm_id)},
        ).mappings().fetchall()
    return [Plot(**row) for row in rows]


@router.get("/{plot_id}", response_model=Plot)
def get_plot(plot_id: str, conn: Db) -> Plot:
    return Plot(**_get_plot(conn, _plot_id(plot_id)))


@router.patch("/{plot_id}", response_model=Plot)
def update_plot(plot_id: str, body: PlotUpdate, conn: Db) -> Plot:
    plot_id = _plot_id(plot_id)
    changes = body.model_dump(exclude_unset=True)
    values = merge(PlotCreate, _get_plot(conn, plot_id), changes).model_dump(mode="json")
    check_references(conn, {field: values[field] for field in changes})
    changed = _write(
        conn,
        f"UPDATE plots SET {', '.join(f'{field} = :{field}' for field in _FIELDS)}"
        " WHERE id = :id",
        {**values, "id": plot_id},
    )
    if changed == 0:
        raise not_found("Plot not found")
    return Plot(id=plot_id, **values)


@router.delete("/{plot_id}", status_code=204, response_class=Response)
def delete_plot(plot_id: str, conn: Db) -> Response:
    plot_id = _plot_id(plot_id)
    if _write(conn, "DELETE FROM plots WHERE id = :id", {"id": plot_id}) == 0:
        raise not_found("Plot not found")
    return Response(status_code=204)
