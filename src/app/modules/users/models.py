from enum import StrEnum

from sqlalchemy import String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin

# The X-API-Key (n8n) acts as this user, so created records have an author.
SERVICE_ACCOUNT_EMAIL = "automation@auto-crm.local"
SERVICE_ACCOUNT_NAME = "Automation (n8n)"


class UserRole(StrEnum):
    ADMIN = "admin"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(String(20), default=UserRole.ADMIN)
    is_active: Mapped[bool] = mapped_column(default=True)
    avatar_key: Mapped[str | None] = mapped_column(String(255))  # object storage key
    # The boss account, created on the setup page (or `uv run superadmin create`). It can view
    # every admin's data and manage admin accounts, but it does no CRM work itself.
    is_super_admin: Mapped[bool] = mapped_column(default=False, server_default=false())
