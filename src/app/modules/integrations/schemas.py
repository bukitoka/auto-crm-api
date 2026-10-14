from pydantic import BaseModel, EmailStr, Field


class LeadIntake(BaseModel):
    """A lead submitted by an external form (via n8n)."""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    company_name: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=5000)
    source: str = Field(default="web_form", max_length=50)
