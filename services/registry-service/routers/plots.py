import sqlite3
from collections.abc import Mapping
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Response

from db import get_db
from errors import not_found, validation
from models import Plot, PlotCreate, PlotUpdate, canonical_uuid, merge

router = APIRouter(prefix="/v1/plots", tags=["plots"])

Db = Annotated[sqlite3.Connection, Depends(get_db)]

_FIELDS = tuple(PlotCreate.model_fields)
_SELECT = f"SELECT id, {', '.join(_FIELDS)} FROM plots"

# Field -> (table, detail). Table names come only from this mapping, never from input.
_REFERENCES = {
    "farm_id": ("farms", "Unknown farm"),
    "crop_id": ("crops", "Unknown crop"),
    "soil_id": ("soils", "Unknown soil"),
    "emitter_id": ("emitters", "Unknown emitter"),
}


def check_references(conn: sqlite3.Connection, values: Mapping[str, Any]) -> None:
    """Raise 422 for the first referenced id in values that does not exist."""
    for field, (table, detail) in _REFERENCES.items():
        if field not in values:
            continue
        row = conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (values[field],)).fetchone()
        if row is None:
            raise validation(detail)


def _write(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> int:
    try:
        with conn:
            return conn.execute(sql, params).rowcount
    except sqlite3.IntegrityError as exc:
        # Safety net: a reference removed between check_references and the write.
        if "FOREIGN KEY" not in str(exc):
            raise
        raise validation("Unknown farm, crop, soil or emitter") from exc


def _plot_id(raw: str) -> str:
    plot_id = canonical_uuid(raw)
    if plot_id is None:
        raise not_found("Plot not found")
    return plot_id


def _get_plot(conn: sqlite3.Connection, plot_id: str) -> sqlite3.Row:
    row = conn.execute(f"{_SELECT} WHERE id = ?", (plot_id,)).fetchone()
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
        f"INSERT INTO plots (id, {', '.join(_FIELDS)}) VALUES (?{', ?' * len(_FIELDS)})",
        (plot_id, *values.values()),
    )
    return Plot(id=plot_id, **values)


@router.get("", response_model=list[Plot])
def list_plots(conn: Db, farm_id: UUID | None = None) -> list[Plot]:
    if farm_id is None:
        rows = conn.execute(f"{_SELECT} ORDER BY rowid").fetchall()
    else:
        rows = conn.execute(
            f"{_SELECT} WHERE farm_id = ? ORDER BY rowid", (str(farm_id),)
        ).fetchall()
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
        f"UPDATE plots SET {', '.join(f'{field} = ?' for field in _FIELDS)} WHERE id = ?",
        (*values.values(), plot_id),
    )
    if changed == 0:
        raise not_found("Plot not found")
    return Plot(id=plot_id, **values)


@router.delete("/{plot_id}", status_code=204, response_class=Response)
def delete_plot(plot_id: str, conn: Db) -> Response:
    plot_id = _plot_id(plot_id)
    if _write(conn, "DELETE FROM plots WHERE id = ?", (plot_id,)) == 0:
        raise not_found("Plot not found")
    return Response(status_code=204)
