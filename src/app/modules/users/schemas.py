import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.users.models import UserRole
from app.shared.schemas import ImageUrl, ORMModel


class UserRead(ORMModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    is_super_admin: bool
    avatar_url: ImageUrl = Field(default=None, validation_alias="avatar_key")
    created_at: datetime
    updated_at: datetime


class UserUpdate(BaseModel):
    """Admin-only changes to a user."""

    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
