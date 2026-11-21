import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.events import Event
from app.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WebhookSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhook_subscriptions"

    event: Mapped[Event] = mapped_column(String(50), index=True)
    target_url: Mapped[str] = mapped_column(String(500))
    secret: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)


class WebhookDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhook_deliveries"

    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("webhook_subscriptions.id", ondelete="SET NULL"), index=True
    )
    event: Mapped[Event] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(default=0)
    delivered: Mapped[bool] = mapped_column(default=False)
    status_code: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(String(200))
