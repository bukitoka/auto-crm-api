import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.modules.users.models import User
from app.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A saved chat with the assistant. Only its owner can change it."""

    __tablename__ = "assistant_conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    is_archived: Mapped[bool] = mapped_column(default=False, index=True)
    message_count: Mapped[int] = mapped_column(default=0)
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    user: Mapped[User] = relationship(lazy="raise")
    messages: Mapped[list[ConversationMessage]] = relationship(
        lazy="raise",
        # UUIDv7 ids are time-ordered: they break ties between messages saved together.
        order_by="(ConversationMessage.created_at, ConversationMessage.id)",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ConversationMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "assistant_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text)
    # What the assistant changed in the CRM during this reply (AssistantAction dicts).
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Charts, metric cards and tables shown under the reply (AssistantBlock dicts).
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # Files the user attached: [{name, text}]. The text is what the model reads.
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
