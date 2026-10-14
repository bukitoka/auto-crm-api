from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import BaseModel

from app.main import app
from app.modules.ai.dependencies import get_ai_client
from app.modules.ai.schemas import EmailDraft, ExtractedContact, LeadScore, TimelineSummary


class FakeAIClient:
    """Stands in for AIClient: returns canned responses and records prompts."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: dict[type[BaseModel], BaseModel] = {
            LeadScore: LeadScore(score=82, reasoning="Engaged decision maker."),
            EmailDraft: EmailDraft(subject="Hello", body="Hi Jane"),
            ExtractedContact: ExtractedContact(first_name="Jane", company_name="Acme"),
        }

    async def complete_json[T: BaseModel](
        self, *, system: str, user: str, schema: type[T], temperature: float = 0.3
    ) -> T:
        self.calls.append({"system": system, "user": user, "schema": schema})
        response = self.responses[schema]
        assert isinstance(response, schema)
        return response


@pytest.fixture
def fake_ai() -> Any:
    fake = FakeAIClient()
    app.dependency_overrides[get_ai_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_ai_client, None)


async def test_score_contact_persists_result(
    client: AsyncClient, admin_headers: dict[str, str], fake_ai: FakeAIClient
) -> None:
    contact = (
        await client.post(
            "/api/v1/contacts",
            json={"first_name": "Jane", "job_title": "CTO"},
            headers=admin_headers,
        )
    ).json()

    response = await client.post(
        f"/api/v1/ai/contacts/{contact['id']}/score", headers=admin_headers
    )

    assert response.status_code == 200
    assert response.json() == {"score": 82, "reasoning": "Engaged decision maker."}
    assert "CTO" in fake_ai.calls[0]["user"]  # context was built from the DB

    saved = (await client.get(f"/api/v1/contacts/{contact['id']}", headers=admin_headers)).json()
    assert saved["ai_score"] == 82
    assert saved["ai_summary"] == "Engaged decision maker."
    assert saved["ai_scored_at"] is not None


async def test_extract_contact(
    client: AsyncClient, admin_headers: dict[str, str], fake_ai: FakeAIClient
) -> None:
    response = await client.post(
        "/api/v1/ai/extract-contact",
        json={"text": "Jane Doe | Acme | jane@acme.com"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["first_name"] == "Jane"
    assert response.json()["email"] is None


async def test_email_draft_for_missing_contact_is_404(
    client: AsyncClient, admin_headers: dict[str, str], fake_ai: FakeAIClient
) -> None:
    response = await client.post(
        "/api/v1/ai/email-draft",
        json={
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "purpose": "Follow up",
        },
        headers=admin_headers,
    )
    assert response.status_code == 404


async def test_ai_disabled_without_api_key(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/ai/extract-contact", json={"text": "anything"}, headers=admin_headers
    )
    assert response.status_code == 503
    assert "DEEPSEEK_API_KEY" in response.json()["detail"]


async def test_summarize_and_email_draft(
    client: AsyncClient, admin_headers: dict[str, str], fake_ai: FakeAIClient
) -> None:
    fake_ai.responses[TimelineSummary] = TimelineSummary(summary="Quiet.", next_actions=["Call"])
    contact = (
        await client.post("/api/v1/contacts", json={"first_name": "Jane"}, headers=admin_headers)
    ).json()
    deal = (
        await client.post(
            "/api/v1/deals",
            json={"title": "Pilot", "contact_id": contact["id"]},
            headers=admin_headers,
        )
    ).json()

    summary = await client.post(
        "/api/v1/ai/summarize", json={"deal_id": deal["id"]}, headers=admin_headers
    )
    draft = await client.post(
        "/api/v1/ai/email-draft",
        json={"contact_id": contact["id"], "deal_id": deal["id"], "purpose": "Follow up"},
        headers=admin_headers,
    )

    assert summary.status_code == 200
    assert summary.json() == {"summary": "Quiet.", "next_actions": ["Call"]}
    assert draft.json() == {"subject": "Hello", "body": "Hi Jane"}
    assert "Pilot" in fake_ai.calls[1]["user"]
