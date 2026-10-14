"""Small "reference" schemas used to nest related objects in responses."""

import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.core.storage import image_url


class ORMModel(BaseModel):
    """Base for response schemas built from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


# A stored image key (e.g. `contacts/<id>/<uuid>.webp`) turned into a browser URL.
# Use it as `avatar_url: ImageUrl = Field(default=None, validation_alias="avatar_key")`.
ImageUrl = Annotated[str | None, AfterValidator(image_url)]


class UserRef(ORMModel):
    id: uuid.UUID
    full_name: str
    avatar_url: ImageUrl = Field(default=None, validation_alias="avatar_key")


class CompanyRef(ORMModel):
    id: uuid.UUID
    name: str


class ContactRef(ORMModel):
    id: uuid.UUID
    first_name: str
    last_name: str | None


class DealRef(ORMModel):
    id: uuid.UUID
    title: str


class StageRef(ORMModel):
    id: uuid.UUID
    name: str
    is_won: bool
    is_lost: bool


def reject_null[T](value: T | None) -> T:
    """Validator helper for PATCH schemas: a field may be omitted, but not set to null."""
    if value is None:
        raise ValueError("This field may not be null")
    return value
