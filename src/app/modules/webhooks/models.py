from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.events import Event
from app.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WebhookSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhook_subscriptions"

    event: Mapped[Event] = mapped_column(String(50), index=True)
    target_url: Mapped[str] = mapped_column(String(500))
    secret: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)
