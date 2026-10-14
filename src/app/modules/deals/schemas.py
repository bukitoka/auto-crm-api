import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.shared.schemas import CompanyRef, ContactRef, ORMModel, StageRef, UserRef, reject_null

Money = Decimal  # input amounts; responses use float for frontend simplicity


class DealCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    value: Money = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    stage_id: uuid.UUID | None = None  # defaults to the first open stage
    contact_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None  # defaults to the current user
    expected_close_date: date | None = None


class DealUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    value: Money | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    stage_id: uuid.UUID | None = None  # same effect (and events) as PATCH /deals/{id}/stage
    contact_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    expected_close_date: date | None = None

    _not_null = field_validator("title", "value", "currency", "stage_id")(reject_null)


class DealStageUpdate(BaseModel):
    stage_id: uuid.UUID


class DealFilters(BaseModel):
    search: str | None = None
    stage_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None


class DealRead(ORMModel):
    id: uuid.UUID
    title: str
    value: float
    currency: str
    stage_id: uuid.UUID
    stage: StageRef
    contact_id: uuid.UUID | None
    contact: ContactRef | None
    company_id: uuid.UUID | None
    company: CompanyRef | None
    owner_id: uuid.UUID | None
    owner: UserRef | None
    expected_close_date: date | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
