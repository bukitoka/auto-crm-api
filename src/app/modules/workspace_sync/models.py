import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SyncImport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_sync_imports"
    __table_args__ = (UniqueConstraint("owner_id", "source_key"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_key: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="SET NULL")
    )
