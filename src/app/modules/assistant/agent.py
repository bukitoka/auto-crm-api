"""Run the model/tool loop without storing conversation messages.

Tool handlers use the request's scoped session and regular CRM services. Expected
validation and business errors are returned to the model so it can correct its call.
Unexpected errors propagate to the request's error handling.
"""

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import BaseMailer
from app.core.exceptions import AppError
from app.modules.ai.client import AIClient
from app.modules.assistant import prompts
from app.modules.assistant.schemas import AssistantReply, PageContext
from app.modules.assistant.tools import TOOLS, ToolContext, tool_specs_for
from app.modules.users.models import User
from app.shared.utils import today_utc

# Model round-trips per user message; each may call several tools.
MAX_STEPS = 8


class ReplyContent(BaseModel):
    reply: str
    title: str | None = None
    summary: str | None = None


class AssistantAgent:
    """Ask the model for a reply, executing permitted tools in the order requested."""

    def __init__(self, session: AsyncSession, ai: AIClient, mailer: BaseMailer) -> None:
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

        draft_only = context is not None and context.type == "meeting"
        specs = tool_specs_for(user, read_only=draft_only)
        allowed_names = {spec["function"]["name"] for spec in specs}
        for _ in range(MAX_STEPS):
            reply = await self.ai.chat(messages=messages, tools=specs, json_reply=True)
            if not reply.tool_calls:
                content = (reply.content or "Done.").strip()
                fenced = re.fullmatch(
                    r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL | re.IGNORECASE
                )
                try:
                    metadata = ReplyContent.model_validate_json(fenced[1] if fenced else content)
                except ValidationError:
                    return AssistantReply(reply=content, actions=ctx.actions, blocks=ctx.blocks)
                return AssistantReply(
                    reply=metadata.reply,
                    title=metadata.title,
                    summary=metadata.summary,
                    actions=ctx.actions,
                    blocks=ctx.blocks,
                )

            # Keep the assistant turn (with its tool calls) in the history, then answer each call.
            messages.append(reply.model_dump(exclude_none=True))
            for call in reply.tool_calls:
                function = getattr(call, "function", None)
                name = function.name if function else ""
                arguments = function.arguments if function else "{}"
                if name not in allowed_names and draft_only:
                    result = {"error": "Meeting drafts cannot change records or send email"}
                else:
                    result = await self._run_tool(ctx, name, arguments)
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": _to_json(result)}
                )

        return AssistantReply(
            reply="That needed more steps than I can do at once. Could you split it up?",
            actions=ctx.actions,
            blocks=ctx.blocks,
        )

    async def _run_tool(self, ctx: ToolContext, name: str, arguments: str) -> dict[str, Any]:
        """Run one tool call. Problems go back to the model as {"error": ...} so it can recover."""
        tool = TOOLS.get(name)
        if tool is None or not tool.allowed_for(ctx.user):
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


def _system_prompt(user: User, context: PageContext | None) -> str:
    today = today_utc()
    context_line = prompts.CONTEXT_LINE.format(type=context.type, id=context.id) if context else ""
    template = prompts.SUPER_ADMIN_SYSTEM if user.is_super_admin else prompts.ADMIN_SYSTEM
    return (template + prompts.VISUALS).format(
        user_name=user.full_name,
        today=today.isoformat(),
        weekday=today.strftime("%A"),
        context=context_line,
    ) + prompts.REPLY_FORMAT


def _to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, default=str, ensure_ascii=False)
