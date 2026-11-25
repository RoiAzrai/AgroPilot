from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from db import get_db
from models import PlotPhotoList

router = APIRouter(prefix="/v1/plot-photos", tags=["plots"])

Db = Annotated[Connection, Depends(get_db)]


@router.get("", response_model=PlotPhotoList)
def list_plot_photos(farm_id: UUID, conn: Db) -> PlotPhotoList:
    """Ids of the farm's plots that have a stored photo. Reads the database only, never S3."""
    rows = conn.execute(
        text(
            "SELECT p.id FROM plots p JOIN plot_photos ph ON ph.plot_id = p.id"
            " WHERE p.farm_id = :farm_id ORDER BY p.rowid"
        ),
        {"farm_id": str(farm_id)},
    ).fetchall()
    return PlotPhotoList(plot_ids=[row[0] for row in rows])
