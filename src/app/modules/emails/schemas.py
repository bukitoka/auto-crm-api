import uuid

from pydantic import BaseModel, Field


class EmailSendRequest(BaseModel):
    contact_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    deal_id: uuid.UUID | None = None  # optionally log the email on a deal too
