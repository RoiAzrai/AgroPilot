from collections.abc import Mapping
from typing import Annotated, Any
from uuid import UUID

from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FarmCreate(RequestBody):
    name: Name


class FarmUpdate(RequestBody):
    name: Name | None = None


class Farm(BaseModel):
    id: UUID
    name: str


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
