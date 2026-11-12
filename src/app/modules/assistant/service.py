"""Manage saved conversations, ownership, and message persistence.

The agent runs CRM tools before the message pair is stored. Keep commits here
explicit: tool recovery can roll back the shared session during a reply.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import BaseMailer
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.modules.ai.client import AIClient
from app.modules.assistant.agent import AssistantAgent
from app.modules.assistant.models import Conversation, ConversationMessage
from app.modules.assistant.repository import ConversationRepository
from app.modules.assistant.schemas import (
    AssistantReply,
    BulkAction,
    BulkResult,
    ChatTurn,
    ConversationFilters,
    ConversationRead,
    ConversationUpdate,
    MessageCreate,
    MessageRead,
    MessageWithFiles,
)
from app.modules.users.models import User
from app.shared.pagination import Page, PageParams
from app.shared.utils import utc_now

# How much of the conversation the model sees.
HISTORY_LIMIT = 20
TITLE_LENGTH = 60


class ConversationService:
    """Keep chats private and store a question and answer only after the agent replies."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ConversationRepository(session)

    async def list_page(
        self, filters: ConversationFilters, params: PageParams, *, user: User
    ) -> Page[ConversationRead]:
        if filters.scope == "all":
            _require_super_admin(user)
            owner = filters.user_id  # None = everyone
        else:
            owner = user.id
        items, total = await self.repo.list_page(
            user_id=owner,
            archived=filters.archived,
            search=filters.search,
            offset=params.offset,
            limit=params.size,
        )
        return Page[ConversationRead].from_items(items, total, params)

    async def get(
        self,
        conversation_id: uuid.UUID,
        *,
        user: User,
        with_messages: bool = False,
    ) -> Conversation:
        """The user's own conversation. The super admin can also read (not change) others'."""
        conversation = await self.repo.get(conversation_id, with_messages=with_messages)
        if conversation is None or not _can_access(user, conversation):
            raise NotFoundError("Conversation not found")
        return conversation

    async def start(
        self, data: MessageCreate, *, user: User, ai: AIClient, mailer: BaseMailer
    ) -> ChatTurn:
        """Create a conversation from the first message and answer it."""
        title = _title_from(data.content or _file_names(data))
        conversation = Conversation(user_id=user.id, title=title)
        await self.repo.add(conversation)
        conversation_id = conversation.id
        # Committed first: a failing tool rolls back the session, which must not lose the chat.
        await self.session.commit()
        try:
            return await self._answer(conversation_id, data, user=user, ai=ai, mailer=mailer)
        except AppError:
            # No reply: don't leave an empty conversation behind.
            await self.session.rollback()
            await self.repo.delete_many([conversation_id])
            await self.session.commit()
            raise

    async def send(
        self,
        conversation_id: uuid.UUID,
        data: MessageCreate,
        *,
        user: User,
        ai: AIClient,
        mailer: BaseMailer,
    ) -> ChatTurn:
        conversation = await self.get(conversation_id, user=user)
        if conversation.user_id != user.id:
            # The super admin can read every chat but not speak in them.
            raise PermissionDeniedError("You can only send messages in your own conversations")
        return await self._answer(conversation.id, data, user=user, ai=ai, mailer=mailer)

    async def _answer(
        self,
        conversation_id: uuid.UUID,
        data: MessageCreate,
        *,
        user: User,
        ai: AIClient,
        mailer: BaseMailer,
    ) -> ChatTurn:
        """Build model history, run tools, then save the completed exchange."""
        previous = await self.repo.recent_messages(conversation_id, HISTORY_LIMIT - 1)
        attachments = _attachments(data)
        history = [
            {"role": message.role, "content": _model_content(message.content, message.attachments)}
            for message in previous
        ]
        history.append({"role": "user", "content": _model_content(data.content, attachments)})

        # If the AI call fails, nothing is stored: the user can simply send again.
        result = await AssistantAgent(self.session, ai, mailer).reply(
            history, user=user, context=data.context
        )
        return await self._save_reply(conversation_id, data.content, attachments, result, user=user)

    async def _save_reply(
        self,
        conversation_id: uuid.UUID,
        content: str,
        attachments: list[dict[str, Any]],
        result: AssistantReply,
        *,
        user: User,
    ) -> ChatTurn:
        """Store both messages together, update the count, and reopen an archived chat."""
        # Reload after tool execution: a failed tool may have rolled back the session.
        conversation = await self.get(conversation_id, user=user)
        question = ConversationMessage(
            conversation_id=conversation.id,
            role="user",
            content=content,
            actions=[],
            attachments=attachments,
        )
        answer = ConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=result.reply,
            actions=[action.model_dump(mode="json") for action in result.actions],
            blocks=[block.model_dump(mode="json") for block in result.blocks],
        )
        await self.repo.add(question)
        await self.repo.add(answer)
        await self.repo.touch(conversation, utc_now(), added=2)
        conversation.is_archived = False  # continuing an archived chat brings it back
        await self.session.commit()

        conversation = await self.get(conversation.id, user=user)
        return ChatTurn(
            conversation=ConversationRead.model_validate(conversation),
            messages=[MessageRead.model_validate(question), MessageRead.model_validate(answer)],
        )

    async def update(
        self, conversation_id: uuid.UUID, data: ConversationUpdate, *, user: User
    ) -> Conversation:
        conversation = await self.get(conversation_id, user=user)
        _require_own(user, conversation)
        for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
            setattr(conversation, field, value)
        await self.session.commit()
        return await self.get(conversation.id, user=user)

    async def delete(self, conversation_id: uuid.UUID, *, user: User) -> None:
        conversation = await self.get(conversation_id, user=user)
        _require_own(user, conversation)
        await self.repo.delete(conversation)
        await self.session.commit()

    async def bulk(self, data: BulkAction, *, user: User) -> BulkResult:
        """Archive / restore / delete many of the user's own conversations."""
        ids = await self.repo.owned_ids(data.ids, user.id)
        if data.action == "delete":
            await self.repo.delete_many(ids)
        else:
            await self.repo.set_archived(ids, data.action == "archive")
        await self.session.commit()
        return BulkResult(affected=len(ids))


def _can_access(user: User, conversation: Conversation) -> bool:
    return conversation.user_id == user.id or user.is_super_admin


def _require_own(user: User, conversation: Conversation) -> None:
    if conversation.user_id != user.id:
        raise PermissionDeniedError("You can only change your own conversations")


def _require_super_admin(user: User) -> None:
    if not user.is_super_admin:
        raise PermissionDeniedError("Only the super admin can read other people's chats")


def _title_from(text: str) -> str:
    """First line of the first message, cut at a word boundary."""
    line = " ".join(text.split())
    if len(line) <= TITLE_LENGTH:
        return line
    return line[:TITLE_LENGTH].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _attachments(data: MessageCreate) -> list[dict[str, Any]]:
    """[{name, text}] of the files sent with the message (only the multipart variant has any)."""
    if not isinstance(data, MessageWithFiles):
        return []
    return [file.model_dump() for file in data.attachments]


def _file_names(data: MessageCreate) -> str:
    return ", ".join(file["name"] for file in _attachments(data))


def _model_content(content: str, attachments: list[dict[str, Any]]) -> str:
    """The user's text plus the text of each attached file, clearly delimited for the model."""
    files = [
        f"[Attached file: {file['name']}]\n{file['text']}\n[End of attached file: {file['name']}]"
        for file in attachments
    ]
    return "\n\n".join(part for part in [content, *files] if part)
