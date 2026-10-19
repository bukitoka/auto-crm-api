import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

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


class AdminCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)


class UserUpdate(BaseModel):
    """What the super admin can change on an admin account. `password` sets a new password."""

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool | None = None
