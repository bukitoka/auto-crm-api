import uuid

from pydantic import BaseModel, EmailStr, Field


class EmailSendRequest(BaseModel):
    contact_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    deal_id: uuid.UUID | None = None  # optionally log the email on a deal too


class NotificationRequest(BaseModel):
    """An internal notice from an automation (n8n) to team members."""

    to: list[EmailStr] = Field(min_length=1, max_length=10)
    subject: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20_000)
