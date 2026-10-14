import uuid
from typing import Self

from pydantic import BaseModel, Field, model_validator

# --- Requests ---


class EmailDraftRequest(BaseModel):
    contact_id: uuid.UUID
    deal_id: uuid.UUID | None = None
    purpose: str = Field(min_length=1, max_length=1000)
    tone: str = Field(default="professional", max_length=100)


class SummarizeRequest(BaseModel):
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def check_target(self) -> Self:
        if self.contact_id is None and self.deal_id is None:
            raise ValueError("Provide a contact_id and/or a deal_id")
        return self


class ExtractContactRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


# --- Responses (also the JSON shapes the model must return) ---


class LeadScore(BaseModel):
    score: int = Field(ge=0, le=100)
    reasoning: str


class EmailDraft(BaseModel):
    subject: str
    body: str


class TimelineSummary(BaseModel):
    summary: str
    next_actions: list[str]


class ExtractedContact(BaseModel):
    """Suggested contact fields; nothing is saved."""

    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    website: str | None = None


class CapturedContact(ExtractedContact):
    """Smart capture from a file: the suggested fields plus the text read from the file."""

    source_text: str
