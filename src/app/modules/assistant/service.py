import json
import logging
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import Mailer
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.modules.ai.client import AIClient
from app.modules.assistant import prompts
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
    PageContext,
)
from app.modules.assistant.tools import TOOL_SPECS, TOOLS, ToolContext
from app.modules.users.models import User
from app.shared.pagination import Page, PageParams
from app.shared.utils import today_utc, utc_now

logger = logging.getLogger(__name__)

# Model round-trips per user message (each may call several tools). Keeps runaway loops cheap.
MAX_STEPS = 8
# How much of the conversation the model sees.
HISTORY_LIMIT = 20
TITLE_LENGTH = 60


class AssistantAgent:
    def __init__(self, session: AsyncSession, ai: AIClient, mailer: Mailer) -> None:
        self.session = session
        self.ai = ai
        self.mailer = mailer

    async def reply(
        self, history: list[dict[str, Any]], *, user: User, context: PageContext | None
    ) -> AssistantReply:
        """Answer the last user message in `history` ([{role, content}, ...])."""
        ctx = ToolContext(self.session, user, self.ai, self.mailer)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _system_prompt(user, context)},
            *history,
        ]

        for _ in range(MAX_STEPS):
            reply = await self.ai.chat(messages=messages, tools=TOOL_SPECS)
            if not reply.tool_calls:
                return AssistantReply(reply=(reply.content or "Done.").strip(), actions=ctx.actions)

            # Keep the assistant turn (with its tool calls) in the history, then answer each call.
            messages.append(reply.model_dump(exclude_none=True))
            for call in reply.tool_calls:
                function = getattr(call, "function", None)
                name = function.name if function else ""
                arguments = function.arguments if function else "{}"
                result = await self._run_tool(ctx, name, arguments)
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": _to_json(result)}
                )

        return AssistantReply(
            reply="That needed more steps than I can do at once. Could you split it up?",
            actions=ctx.actions,
        )

    async def _run_tool(self, ctx: ToolContext, name: str, arguments: str) -> dict[str, Any]:
        """Run one tool call. Problems go back to the model as {"error": ...} so it can recover."""
        tool = TOOLS.get(name)
        if tool is None:
            return {"error": f"Unknown tool {name!r}"}
        try:
            params = tool.params.model_validate_json(arguments or "{}")
            return await tool.handler(ctx, params)
        except ValidationError as exc:
            return {"error": f"Invalid arguments: {exc.errors(include_url=False)}"}
        except AppError as exc:
            # Undo anything half-done, then reload the user (a rollback expires loaded objects).
            await self.session.rollback()
            await self.session.refresh(ctx.user)
            return {"error": exc.message}


class ConversationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ConversationRepository(session)

    # --- Reading ---

    async def list_page(
        self, filters: ConversationFilters, params: PageParams, *, user: User
    ) -> Page[ConversationRead]:
        if filters.scope == "all":
            _require_admin(user)
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
        self, conversation_id: uuid.UUID, *, user: User, with_messages: bool = False
    ) -> Conversation:
        """A conversation the user may see: their own, or any for admins (404 otherwise)."""
        conversation = await self.repo.get(conversation_id, with_messages=with_messages)
        if conversation is None or not _can_manage(user, conversation):
            raise NotFoundError("Conversation not found")
        return conversation

    # --- Chatting ---

    async def start(
        self, data: MessageCreate, *, user: User, ai: AIClient, mailer: Mailer
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
        mailer: Mailer,
    ) -> ChatTurn:
        conversation = await self.get(conversation_id, user=user)
        if conversation.user_id != user.id:
            # Admins can read and manage anyone's chats, but not speak in them.
            raise PermissionDeniedError("You can only send messages in your own conversations")
        return await self._answer(conversation.id, data, user=user, ai=ai, mailer=mailer)

    async def _answer(
        self,
        conversation_id: uuid.UUID,
        data: MessageCreate,
        *,
        user: User,
        ai: AIClient,
        mailer: Mailer,
    ) -> ChatTurn:
        previous = await self.repo.recent_messages(conversation_id, HISTORY_LIMIT - 1)
        attachments = _attachments(data)
        history = [
            {"role": m.role, "content": _model_content(m.content, m.attachments)} for m in previous
        ]
        history.append({"role": "user", "content": _model_content(data.content, attachments)})

        # If the AI call fails, nothing is stored: the user can simply send again.
        result = await AssistantAgent(self.session, ai, mailer).reply(
            history, user=user, context=data.context
        )

        conversation = await self.get(conversation_id, user=user)
        question = ConversationMessage(
            conversation_id=conversation.id,
            role="user",
            content=data.content,
            actions=[],
            attachments=attachments,
        )
        answer = ConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=result.reply,
            actions=[action.model_dump(mode="json") for action in result.actions],
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

    # --- Managing ---

    async def update(
        self, conversation_id: uuid.UUID, data: ConversationUpdate, *, user: User
    ) -> Conversation:
        conversation = await self.get(conversation_id, user=user)
        for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
            setattr(conversation, field, value)
        await self.session.commit()
        return await self.get(conversation.id, user=user)

    async def delete(self, conversation_id: uuid.UUID, *, user: User) -> None:
        conversation = await self.get(conversation_id, user=user)
        await self.repo.delete(conversation)
        await self.session.commit()

    async def bulk(self, data: BulkAction, *, user: User) -> BulkResult:
        """Archive / restore / delete many. Admins may touch anyone's; others only their own."""
        owner = None if user.is_admin else user.id
        ids = await self.repo.owned_ids(data.ids, owner)
        if data.action == "delete":
            await self.repo.delete_many(ids)
        else:
            await self.repo.set_archived(ids, data.action == "archive")
        await self.session.commit()
        return BulkResult(affected=len(ids))


def _can_manage(user: User, conversation: Conversation) -> bool:
    return conversation.user_id == user.id or user.is_admin


def _require_admin(user: User) -> None:
    if not user.is_admin:
        raise PermissionDeniedError("Admin privileges required")


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


def _system_prompt(user: User, context: PageContext | None) -> str:
    today = today_utc()
    context_line = prompts.CONTEXT_LINE.format(type=context.type, id=context.id) if context else ""
    return prompts.ASSISTANT_SYSTEM.format(
        user_name=user.full_name,
        user_role=user.role,
        today=today.isoformat(),
        weekday=today.strftime("%A"),
        context=context_line,
    )


def _to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, default=str, ensure_ascii=False)
