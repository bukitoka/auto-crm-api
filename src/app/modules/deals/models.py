import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.companies.models import Company
from app.modules.contacts.models import Contact
from app.modules.pipeline.models import PipelineStage
from app.modules.users.models import User
from app.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Deal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "deals"

    title: Mapped[str] = mapped_column(String(200))
    value: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal(0))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    stage_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_stages.id", ondelete="RESTRICT"), index=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    stage: Mapped[PipelineStage] = relationship(lazy="raise")
    contact: Mapped[Contact | None] = relationship(lazy="raise")
    company: Mapped[Company | None] = relationship(lazy="raise")
    owner: Mapped[User | None] = relationship(lazy="raise")
