import re
from collections.abc import Mapping
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi.exceptions import RequestValidationError
from pydantic import (
    AfterValidator,
    AllowInfNan,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StringConstraints,
    Strict,
    ValidationError,
)

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


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


# The single definition of a plot's fields. FR-1.3 rules attach here.
class PlotCreate(RequestBody):
    farm_id: UuidString
    name: Name
    area_m2: Number
    crop_id: str
    planting_date: IsoDate
    soil_id: str
    row_spacing_m: Number
    emitter_spacing_m: Number
    emitter_id: str
    lat: Number
    lon: Number


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


class Plot(PlotCreate):
    id: UUID


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
