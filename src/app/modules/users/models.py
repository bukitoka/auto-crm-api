from enum import StrEnum

from sqlalchemy import String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(String(20), default=UserRole.MEMBER)
    is_active: Mapped[bool] = mapped_column(default=True)
    avatar_key: Mapped[str | None] = mapped_column(String(255))  # object storage key
    # Created on the setup page (or `uv run superadmin create`). Has every permission and is not
    # part of the team: hidden from user lists, pickers and the dashboard.
    is_super_admin: Mapped[bool] = mapped_column(default=False, server_default=false())

    @property
    def is_admin(self) -> bool:
        return self.is_super_admin or self.role == UserRole.ADMIN
