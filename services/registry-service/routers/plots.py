import logging
from collections.abc import Mapping
from typing import Annotated, Any
from uuid import UUID, uuid4

import boto3
import sqlalchemy.exc
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, Request, Response, UploadFile
from sqlalchemy import Connection, RowMapping, text

from config import Settings
from db import get_db, is_foreign_key_violation
from errors import not_found, unavailable, validation
from models import Plot, PlotCreate, PlotPhoto, PlotUpdate, canonical_uuid, merge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/plots", tags=["plots"])

MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MiB
PHOTO_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

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
    # Write only the sent fields, so a concurrent PATCH of other fields is not overwritten.
    # Column names come from _FIELDS, never from the request.
    columns = [field for field in _FIELDS if field in changes]
    if columns:
        changed = _write(
            conn,
            f"UPDATE plots SET {', '.join(f'{field} = :{field}' for field in columns)}"
            " WHERE id = :id",
            {**{field: values[field] for field in columns}, "id": plot_id},
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


def _s3_client(settings: Settings):
    """A new S3 client per request. No credentials are passed: boto3 finds them
    (~/.aws locally, the instance's IAM role on EC2)."""
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        config=Config(
            connect_timeout=settings.s3_connect_timeout_seconds,
            read_timeout=settings.s3_read_timeout_seconds,
            retries={"max_attempts": settings.s3_max_attempts, "mode": "standard"},
        ),
    )


def _read_photo(file: UploadFile) -> bytes:
    """The file's bytes, or 422 if it is empty, too big or not an allowed image type."""
    if file.content_type not in PHOTO_CONTENT_TYPES:
        raise validation("Photo must be image/jpeg, image/png or image/webp")
    data = file.file.read(MAX_PHOTO_BYTES + 1)
    if not data:
        raise validation("Photo is empty")
    if len(data) > MAX_PHOTO_BYTES:
        raise validation("Photo is larger than 5 MB")
    return data


# Sync handlers on purpose: the database and boto3 calls block, so FastAPI runs them
# in its threadpool instead of on the event loop.
@router.post("/{plot_id}/photo", status_code=201, response_model=PlotPhoto)
def upload_photo(plot_id: str, file: UploadFile, request: Request, conn: Db) -> PlotPhoto:
    plot_id = _plot_id(plot_id)
    plot = _get_plot(conn, plot_id)
    data = _read_photo(file)
    key = f"{plot['farm_id']}/{plot_id}/photo"
    settings = request.app.state.settings
    # End the read transaction: PostgreSQL would hold it open during the S3 call.
    conn.rollback()
    try:
        _s3_client(settings).put_object(
            Bucket=settings.aws_s3_bucket, Key=key, Body=data, ContentType=file.content_type
        )
    except (BotoCoreError, ClientError) as exc:
        logger.warning("S3 upload failed for plot %s (key %s): %r", plot_id, key, exc)
        raise unavailable("Photo storage unavailable") from exc
    # Written only after S3 succeeded, so a failed upload leaves the stored key unchanged.
    try:
        conn.execute(
            text(
                "INSERT INTO plot_photos (plot_id, key, content_type)"
                " VALUES (:plot_id, :key, :content_type)"
                " ON CONFLICT (plot_id) DO UPDATE"
                " SET key = excluded.key, content_type = excluded.content_type"
            ),
            {"plot_id": plot_id, "key": key, "content_type": file.content_type},
        )
        conn.commit()
    except sqlalchemy.exc.IntegrityError as exc:
        # The plot was deleted during the upload.
        if not is_foreign_key_violation(exc.orig):
            raise
        raise not_found("Plot not found") from exc
    return PlotPhoto(plot_id=plot_id, key=key, content_type=file.content_type)


@router.get(
    "/{plot_id}/photo",
    response_class=Response,
    responses={200: {"content": {content_type: {} for content_type in sorted(PHOTO_CONTENT_TYPES)}}},
)
def get_photo(plot_id: str, request: Request, conn: Db) -> Response:
    plot_id = _plot_id(plot_id)
    _get_plot(conn, plot_id)
    photo = conn.execute(
        text("SELECT key, content_type FROM plot_photos WHERE plot_id = :plot_id"),
        {"plot_id": plot_id},
    ).mappings().fetchone()
    if photo is None:
        raise not_found("Plot has no photo")
    settings = request.app.state.settings
    conn.rollback()  # end the read transaction before the S3 call
    try:
        obj = _s3_client(settings).get_object(Bucket=settings.aws_s3_bucket, Key=photo["key"])
        data = obj["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        # A missing object is also here: without s3:ListBucket, S3 answers 403, not 404.
        logger.warning(
            "S3 download failed for plot %s (key %s): %r", plot_id, photo["key"], exc
        )
        raise unavailable("Photo storage unavailable") from exc
    return Response(
        content=data,
        media_type=photo["content_type"],
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )
