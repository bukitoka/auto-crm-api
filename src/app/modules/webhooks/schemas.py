import uuid
from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, field_validator

from app.core.events import Event
from app.shared.schemas import ORMModel, reject_null


class WebhookCreate(BaseModel):
    event: Event
    target_url: AnyHttpUrl
    is_active: bool = True


class WebhookUpdate(BaseModel):
    event: Event | None = None
    target_url: AnyHttpUrl | None = None
    is_active: bool | None = None

    _not_null = field_validator("event", "target_url", "is_active")(reject_null)


class WebhookRead(ORMModel):
    id: uuid.UUID
    event: Event
    target_url: str
    secret: str  # used by the receiver to verify X-AutoCRM-Signature
    is_active: bool
    created_at: datetime
    updated_at: datetime
