import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.modules.assistant.models import Conversation, ConversationMessage
from app.shared.utils import like_pattern


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, conversation_id: uuid.UUID, *, with_messages: bool = False):
        query = (
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(joinedload(Conversation.user))
            .execution_options(populate_existing=True)
        )
        if with_messages:
            query = query.options(selectinload(Conversation.messages))
        return (await self.session.execute(query)).scalar_one_or_none()

    async def list_page(
        self,
        *,
        user_id: uuid.UUID | None,
        archived: bool,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Conversation], int]:
        """`user_id=None` means every user's conversations (admins only)."""
        query = select(Conversation).where(Conversation.is_archived == archived)
        if user_id is not None:
            query = query.where(Conversation.user_id == user_id)
        if search:
            query = query.where(Conversation.title.ilike(like_pattern(search)))

        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            query.options(joinedload(Conversation.user))
            .order_by(Conversation.last_message_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars()), total or 0

    async def recent_messages(
        self, conversation_id: uuid.UUID, limit: int
    ) -> list[ConversationMessage]:
        """The last `limit` messages, oldest first (the order the model reads them)."""
        result = await self.session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def add(self, item: Conversation | ConversationMessage) -> None:
        self.session.add(item)
        await self.session.flush()

    async def delete(self, conversation: Conversation) -> None:
        await self.session.delete(conversation)
        await self.session.flush()

    async def owned_ids(self, ids: list[uuid.UUID], user_id: uuid.UUID | None) -> list[uuid.UUID]:
        """Which of `ids` exist (and belong to `user_id`, unless it is None)."""
        query = select(Conversation.id).where(Conversation.id.in_(ids))
        if user_id is not None:
            query = query.where(Conversation.user_id == user_id)
        return list((await self.session.execute(query)).scalars())

    async def set_archived(self, ids: list[uuid.UUID], archived: bool) -> None:
        await self.session.execute(
            update(Conversation).where(Conversation.id.in_(ids)).values(is_archived=archived)
        )

    async def delete_many(self, ids: list[uuid.UUID]) -> None:
        await self.session.execute(delete(Conversation).where(Conversation.id.in_(ids)))

    async def touch(self, conversation: Conversation, at: datetime, added: int) -> None:
        conversation.last_message_at = at
        conversation.message_count += added
