import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.modules.contacts.models import ContactStatus
from app.shared.schemas import CompanyRef, ImageUrl, ORMModel, UserRef, reject_null


class ContactCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    job_title: str | None = Field(default=None, max_length=150)
    status: ContactStatus = ContactStatus.LEAD
    source: str = Field(default="manual", max_length=50)
    tags: list[str] = []
    company_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None  # defaults to the current user


class ContactUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    job_title: str | None = Field(default=None, max_length=150)
    status: ContactStatus | None = None
    source: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = None
    company_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None

    _not_null = field_validator("first_name", "status", "source", "tags")(reject_null)


class ContactFilters(BaseModel):
    search: str | None = None
    status: ContactStatus | None = None
    company_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None


class ContactRead(ORMModel):
    id: uuid.UUID
    first_name: str
    last_name: str | None
    email: str | None
    phone: str | None
    job_title: str | None
    status: ContactStatus
    source: str
    tags: list[str]
    avatar_url: ImageUrl = Field(default=None, validation_alias="avatar_key")
    company_id: uuid.UUID | None
    company: CompanyRef | None
    owner_id: uuid.UUID | None
    owner: UserRef | None
    ai_score: int | None
    ai_summary: str | None
    ai_scored_at: datetime | None
    created_at: datetime
    updated_at: datetime
