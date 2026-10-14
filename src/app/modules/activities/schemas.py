import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.modules.activities.models import ActivityType
from app.shared.schemas import ContactRef, DealRef, ORMModel, UserRef


class ActivityCreate(BaseModel):
    type: ActivityType
    subject: str = Field(min_length=1, max_length=200)
    body: str | None = None
    occurred_at: datetime | None = None  # defaults to now
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def check_target(self) -> Self:
        if self.contact_id is None and self.deal_id is None:
            raise ValueError("An activity needs a contact_id and/or a deal_id")
        return self


class ActivityFilters(BaseModel):
    search: str | None = None
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None
    type: ActivityType | None = None


class ActivityRead(ORMModel):
    id: uuid.UUID
    type: ActivityType
    subject: str
    body: str | None
    occurred_at: datetime
    contact_id: uuid.UUID | None
    contact: ContactRef | None
    deal_id: uuid.UUID | None
    deal: DealRef | None
    created_by_id: uuid.UUID | None
    created_by: UserRef | None
    created_at: datetime
    updated_at: datetime
