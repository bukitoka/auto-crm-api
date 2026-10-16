import asyncio
import json
from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest
from pydantic import BaseModel

from app.core.config import settings
from app.core.exceptions import AIResponseError, NotFoundError, ServiceUnavailableError
from app.modules.ai import client as ai_client
from app.modules.ai import dependencies, prompts
from app.modules.ai.client import AIClient
from app.modules.ai.schemas import (
    EmailDraft,
    EmailDraftRequest,
    ExtractContactRequest,
    ExtractedContact,
    LeadScore,
    SummarizeRequest,
    TimelineSummary,
)
from app.modules.ai.service import MAX_BODY_CHARS, AIService
from tests.unit.conftest import (
    make_activity,
    make_company,
    make_contact,
    make_deal,
    make_stage,
    mock_repos,
)

# --- AIClient ---


def _client_returning(content: str | None) -> AIClient:
    client = AIClient(api_key="key", base_url="http://ai.local", model="test-model")
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(return_value=reply)
    return client


async def test_complete_json_returns_the_validated_object() -> None:
    client = _client_returning('{"score": 80, "reasoning": "Good fit"}')

    result = await client.complete_json(system="sys", user="usr", schema=LeadScore)

    assert result == LeadScore(score=80, reasoning="Good fit")
    call = client._client.chat.completions.create.call_args.kwargs
    assert call["model"] == "test-model"
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}  # thinking takes minutes
    assert call["max_tokens"] > 0
    assert call["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("this is not json", id="invalid-json"),
        pytest.param('{"score": 80}', id="missing-field"),
        pytest.param('{"score": 500, "reasoning": "x"}', id="out-of-range"),
        pytest.param(None, id="empty-reply"),
    ],
)
async def test_complete_json_maps_invalid_output_to_502(content: str | None) -> None:
    client = _client_returning(content)

    with pytest.raises(AIResponseError) as error:
        await client.complete_json(system="s", user="u", schema=LeadScore)
    assert error.value.status_code == 502


async def test_complete_json_maps_provider_errors_to_502() -> None:
    client = _client_returning("{}")
    client._client.chat.completions.create.side_effect = openai.APIConnectionError(
        request=MagicMock()
    )

    with pytest.raises(AIResponseError, match="request failed"):
        await client.complete_json(system="s", user="u", schema=LeadScore)


async def test_chat_sends_tools_and_returns_the_message() -> None:
    client = _client_returning("Hello!")
    tools = [{"type": "function", "function": {"name": "search_contacts"}}]

    message = await client.chat(messages=[{"role": "user", "content": "Hi"}], tools=tools)

    assert message.content == "Hello!"
    call = client._client.chat.completions.create.call_args.kwargs
    assert call["tools"] == tools
    assert call["messages"] == [{"role": "user", "content": "Hi"}]
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}


async def test_chat_maps_provider_errors_to_502() -> None:
    client = _client_returning(None)
    client._client.chat.completions.create.side_effect = openai.APIConnectionError(
        request=MagicMock()
    )

    with pytest.raises(AIResponseError, match="request failed"):
        await client.chat(messages=[], tools=[])


async def test_a_stuck_provider_call_times_out_with_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_client, "REQUEST_DEADLINE_SECONDS", 0.01)
    client = _client_returning(None)

    async def never_answers(**_: Any) -> None:
        await asyncio.sleep(1)

    client._client.chat.completions.create.side_effect = never_answers

    with pytest.raises(AIResponseError, match="took too long"):
        await client.complete_json(system="s", user="u", schema=LeadScore)


# --- get_ai_client ---


def test_missing_api_key_disables_ai_with_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    with pytest.raises(ServiceUnavailableError, match="DEEPSEEK_API_KEY") as error:
        dependencies.get_ai_client()
    assert error.value.status_code == 503


def test_configured_api_key_returns_a_cached_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test")

    client = dependencies.get_ai_client()

    assert isinstance(client, AIClient)
    assert client.model == settings.deepseek_model
    assert dependencies.get_ai_client() is client


# --- AIService ---


class FakeAIClient:
    """Returns a canned answer per schema and records the prompts it was given."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.answers: dict[type[BaseModel], BaseModel] = {
            LeadScore: LeadScore(score=72, reasoning="Engaged buyer."),
            EmailDraft: EmailDraft(subject="Hello", body="Hi Jane"),
            TimelineSummary: TimelineSummary(summary="All good.", next_actions=["Call"]),
            ExtractedContact: ExtractedContact(first_name="Jane"),
        }

    async def complete_json(
        self, *, system: str, user: str, schema: type[BaseModel], **kwargs: Any
    ) -> Any:
        self.calls.append({"system": system, "user": user, "schema": schema, **kwargs})
        return self.answers[schema]


@pytest.fixture
def fake_ai() -> FakeAIClient:
    return FakeAIClient()


@pytest.fixture
def service(session: AsyncMock, fake_ai: FakeAIClient) -> AIService:
    # FakeAIClient has the same `complete_json` as AIClient (duck typing).
    service = AIService(session, fake_ai)  # ty: ignore[invalid-argument-type]
    mock_repos(service, "contacts", "deals", "activities")
    service.deals.list_for_contact.return_value = []
    service.activities.list_recent.return_value = []
    return service


def _context(call: dict[str, Any], template: str) -> dict[str, Any]:
    """Parse the JSON context back out of a user prompt."""
    prefix = template.split("{context}")[0]
    assert call["user"].startswith(prefix)
    return json.loads(call["user"][len(prefix) :])


async def test_score_contact_builds_context_and_saves_result(
    service: AIService, fake_ai: FakeAIClient
) -> None:
    contact = make_contact(
        first_name="Jane", last_name="Doe", job_title="CTO", company=make_company(name="Acme")
    )
    service.contacts.get.return_value = contact
    service.deals.list_for_contact.return_value = [
        make_deal(
            stage=make_stage("Proposal"), title="Renewal", expected_close_date=date(2026, 3, 1)
        )
    ]
    service.activities.list_recent.return_value = [make_activity(subject="Demo")]

    result = await service.score_contact(contact.id)

    assert result.score == 72
    assert (contact.ai_score, contact.ai_summary) == (72, "Engaged buyer.")
    assert contact.ai_scored_at is not None
    service.session.commit.assert_awaited_once()

    call = fake_ai.calls[0]
    assert call["system"] == prompts.LEAD_SCORE_SYSTEM
    context = _context(call, prompts.LEAD_SCORE_USER)
    assert context["contact"]["name"] == "Jane Doe"
    assert context["contact"]["company"] == "Acme"
    assert context["deals"] == [
        {
            "title": "Renewal",
            "value": 1000.0,
            "currency": "USD",
            "stage": "Proposal",
            "expected_close_date": "2026-03-01",
        }
    ]
    assert context["activities"][0]["subject"] == "Demo"


async def test_score_unknown_contact_is_not_found(service: AIService) -> None:
    service.contacts.get.return_value = None

    with pytest.raises(NotFoundError, match="Contact not found"):
        await service.score_contact(make_contact().id)


async def test_activity_bodies_are_truncated_in_the_prompt(
    service: AIService, fake_ai: FakeAIClient
) -> None:
    contact = make_contact()
    service.contacts.get.return_value = contact
    service.activities.list_recent.return_value = [make_activity(body="x" * 2000)]

    await service.score_contact(contact.id)

    context = _context(fake_ai.calls[0], prompts.LEAD_SCORE_USER)
    assert len(context["activities"][0]["body"]) == MAX_BODY_CHARS


async def test_email_draft_includes_purpose_tone_and_deal(
    service: AIService, fake_ai: FakeAIClient
) -> None:
    contact = make_contact()
    deal = make_deal(title="Pilot")
    service.contacts.get.return_value = contact
    service.deals.get.return_value = deal

    draft = await service.draft_email(
        EmailDraftRequest(contact_id=contact.id, deal_id=deal.id, purpose="Book a demo")
    )

    assert draft.subject == "Hello"
    call = fake_ai.calls[0]
    assert "Purpose of the email: Book a demo" in call["user"]
    assert "Tone: professional" in call["user"]
    assert '"title": "Pilot"' in call["user"]
    assert call["temperature"] == 0.7


async def test_email_draft_for_unknown_deal_is_not_found(service: AIService) -> None:
    service.contacts.get.return_value = make_contact()
    service.deals.get.return_value = None

    with pytest.raises(NotFoundError, match="Deal not found"):
        await service.draft_email(
            EmailDraftRequest(contact_id=make_contact().id, deal_id=make_deal().id, purpose="x")
        )


async def test_summarize_a_deal_only(service: AIService, fake_ai: FakeAIClient) -> None:
    deal = make_deal(title="Expansion")
    service.deals.get.return_value = deal

    result = await service.summarize(SummarizeRequest(deal_id=deal.id))

    assert result.next_actions == ["Call"]
    context = _context(fake_ai.calls[0], prompts.SUMMARY_USER)
    assert set(context) == {"deal", "activities"}
    service.activities.list_recent.assert_awaited_once_with(
        limit=30, contact_id=None, deal_id=deal.id
    )


async def test_summarize_a_contact(service: AIService, fake_ai: FakeAIClient) -> None:
    contact = make_contact()
    service.contacts.get.return_value = contact

    await service.summarize(SummarizeRequest(contact_id=contact.id))

    assert "contact" in _context(fake_ai.calls[0], prompts.SUMMARY_USER)


async def test_extract_contact_passes_the_text_unchanged(
    service: AIService, fake_ai: FakeAIClient
) -> None:
    result = await service.extract_contact(ExtractContactRequest(text="Jane | Acme"))

    assert result.first_name == "Jane"
    assert fake_ai.calls[0]["user"] == "Text:\nJane | Acme"
    assert fake_ai.calls[0]["temperature"] == 0.0
