import uuid
from typing import Self

from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.companies.models import Company
from app.modules.contacts.models import Contact
from app.modules.deals.models import Deal

RECORD_MODELS = {"contact_id": Contact, "company_id": Company, "deal_id": Deal}


class RecordLinks(BaseModel):
    contact_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def one_record(self) -> Self:
        if sum(getattr(self, key) is not None for key in RECORD_MODELS) > 1:
            raise ValueError("Select one linked CRM record")
        return self


async def validate_link(session: AsyncSession, links: RecordLinks) -> None:
    for key, model in RECORD_MODELS.items():
        record_id = getattr(links, key)
        if (
            record_id is not None
            and await session.scalar(select(model.id).where(model.id == record_id)) is None
        ):
            raise NotFoundError("Linked record not found")
