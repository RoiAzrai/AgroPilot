import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi.exceptions import RequestValidationError
from pydantic import (
    AfterValidator,
    AllowInfNan,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    Strict,
    ValidationError,
)
from pydantic_core import PydanticCustomError

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# The earliest time zone on Earth: its date is the latest date that has started anywhere.
UTC_PLUS_14 = timezone(timedelta(hours=14))


def _utc_now() -> datetime:
    """The only place that reads the clock; tests monkeypatch it."""
    return datetime.now(timezone.utc)


def latest_date_on_earth() -> date:
    """The current date in UTC+14."""
    return _utc_now().astimezone(UTC_PLUS_14).date()


def _not_in_future(value: date) -> date:
    # Looked up at call time, so tests can monkeypatch latest_date_on_earth.
    if value > latest_date_on_earth():
        raise PydanticCustomError("date_in_future", "cannot be in the future")
    return value


def _iso_date_string(value: Any) -> Any:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise ValueError("Date must be a YYYY-MM-DD string")
    return value


def _uuid_string(value: str) -> str:
    canonical = canonical_uuid(value)
    if canonical is None:
        raise ValueError("Input should be a valid UUID")
    return canonical


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# Strict rejects "1000" and true but still accepts the integer 1000 for a float.
Number = Annotated[float, Strict(), AllowInfNan(False)]
IsoDate = Annotated[date, BeforeValidator(_iso_date_string)]
UuidString = Annotated[str, Strict(), AfterValidator(_uuid_string)]


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FarmCreate(RequestBody):
    name: Name


class FarmUpdate(RequestBody):
    name: Name | None = None


class Farm(BaseModel):
    id: UUID
    name: str


# The single place for a plot's rules (FR-1.3). PATCH applies them through merge().
class PlotCreate(RequestBody):
    farm_id: UuidString
    name: Name
    area_m2: Annotated[Number, Field(gt=0)]
    crop_id: str
    planting_date: Annotated[IsoDate, AfterValidator(_not_in_future)]
    soil_id: str
    row_spacing_m: Annotated[Number, Field(gt=0)]
    emitter_spacing_m: Annotated[Number, Field(gt=0)]
    emitter_id: str
    lat: Annotated[Number, Field(ge=-90, le=90)]
    lon: Annotated[Number, Field(ge=-180, le=180)]


class PlotUpdate(RequestBody):
    farm_id: UuidString | None = None
    name: Name | None = None
    area_m2: Number | None = None
    crop_id: str | None = None
    planting_date: IsoDate | None = None
    soil_id: str | None = None
    row_spacing_m: Number | None = None
    emitter_spacing_m: Number | None = None
    emitter_id: str | None = None
    lat: Number | None = None
    lon: Number | None = None


# Response shape only: stored plots are not re-validated against the input rules.
class Plot(BaseModel):
    id: UUID
    farm_id: UUID
    name: str
    area_m2: float
    crop_id: str
    planting_date: date
    soil_id: str
    row_spacing_m: float
    emitter_spacing_m: float
    emitter_id: str
    lat: float
    lon: float


def canonical_uuid(value: str) -> str | None:
    """Return the lowercase canonical form of a UUID of any version, or None."""
    try:
        return str(UUID(value))
    except ValueError:
        return None


def merge[M: BaseModel](model: type[M], current: Mapping[str, Any], changes: dict[str, Any]) -> M:
    """Apply a PATCH to a stored record and validate the result as a whole."""
    data = {field: current[field] for field in model.model_fields} | changes
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise RequestValidationError(
            [{**error, "loc": ("body", *error["loc"])} for error in exc.errors()]
        ) from exc
