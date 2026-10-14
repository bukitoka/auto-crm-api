import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.companies.models import Company
from app.modules.users.models import User
from app.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ContactStatus(StrEnum):
    LEAD = "lead"
    PROSPECT = "prospect"
    CUSTOMER = "customer"
    CHURNED = "churned"


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contacts"

    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(50))
    job_title: Mapped[str | None] = mapped_column(String(150))
    status: Mapped[ContactStatus] = mapped_column(
        String(20), default=ContactStatus.LEAD, index=True
    )
    source: Mapped[str] = mapped_column(String(50), default="manual")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list)
    avatar_key: Mapped[str | None] = mapped_column(String(255))  # object storage key

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    ai_score: Mapped[int | None]
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company | None] = relationship(lazy="raise")
    owner: Mapped[User | None] = relationship(lazy="raise")
