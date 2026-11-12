import json
from unittest.mock import AsyncMock

import pytest

from app.modules.ai.client import AIClient
from app.modules.assistant.agent import AssistantAgent
from app.modules.assistant.tools import TOOLS, Tool, ToolContext
from tests.fakes import FakeMailer
from tests.unit.conftest import make_user


async def test_unexpected_tool_failure_propagates(
    session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Programming errors must not be disguised as recoverable model mistakes."""
    user = make_user()
    ai = AsyncMock(spec=AIClient)
    mailer = FakeMailer()
    agent = AssistantAgent(session, ai, mailer)
    context = ToolContext(session, user, ai, mailer)
    original = TOOLS["get_contact"]
    handler = AsyncMock(side_effect=RuntimeError("unexpected storage failure"))
    monkeypatch.setitem(
        TOOLS,
        original.name,
        Tool(original.name, original.description, original.params, handler),
    )
    arguments = json.dumps({"contact_id": str(user.id)})

    with pytest.raises(RuntimeError, match="unexpected storage failure"):
        await agent._run_tool(context, "get_contact", arguments)

    handler.assert_awaited_once()
    session.rollback.assert_not_awaited()
