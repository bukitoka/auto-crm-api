import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.shared.schemas import ImageUrl, ORMModel, UserRef, reject_null
from app.shared.sorting import SortOrder


class CompanyBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=100)
    size: str | None = Field(default=None, max_length=50)
    website: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class CompanyCreate(CompanyBase):
    owner_id: uuid.UUID | None = None  # defaults to the current user


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=100)
    size: str | None = Field(default=None, max_length=50)
    website: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    owner_id: uuid.UUID | None = None

    _not_null = field_validator("name")(reject_null)


class CompanyFilters(BaseModel):
    search: str | None = None
    industry: str | None = None
    sort: Literal["name", "industry", "created_at"] | None = None
    order: SortOrder = SortOrder.ASC


class CompanyRead(ORMModel):
    id: uuid.UUID
    name: str
    domain: str | None
    industry: str | None
    size: str | None
    website: str | None
    notes: str | None
    logo_url: ImageUrl = Field(default=None, validation_alias="logo_key")
    owner_id: uuid.UUID | None
    owner: UserRef | None
    created_at: datetime
    updated_at: datetime
