"""AI features: builds context from CRM data, calls the model, stores results."""

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.activities.models import Activity
from app.modules.activities.repository import ActivityRepository
from app.modules.ai import prompts
from app.modules.ai.client import AIClient
from app.modules.ai.schemas import (
    CapturedContact,
    EmailDraft,
    EmailDraftRequest,
    ExtractContactRequest,
    ExtractedContact,
    LeadScore,
    SummarizeRequest,
    TimelineSummary,
)
from app.modules.contacts.models import Contact
from app.modules.contacts.repository import ContactRepository
from app.modules.deals.models import Deal
from app.modules.deals.repository import DealRepository
from app.shared.utils import utc_now

MAX_ACTIVITIES = 30
MAX_BODY_CHARS = 500


class AIService:
    def __init__(self, session: AsyncSession, ai: AIClient) -> None:
        self.session = session
        self.ai = ai
        self.contacts = ContactRepository(session)
        self.deals = DealRepository(session)
        self.activities = ActivityRepository(session)

    async def score_contact(self, contact_id: uuid.UUID) -> LeadScore:
        """Score a contact 0-100 and save the result on the contact."""
        contact = await self._get_contact(contact_id)
        deals = await self.deals.list_for_contact(contact.id)
        activities = await self.activities.list_recent(limit=MAX_ACTIVITIES, contact_id=contact.id)
        context = {
            "contact": _contact_data(contact),
            "deals": [_deal_data(deal) for deal in deals],
            "activities": [_activity_data(a) for a in activities],
        }
        result = await self.ai.complete_json(
            system=prompts.LEAD_SCORE_SYSTEM,
            user=prompts.LEAD_SCORE_USER.format(context=_to_json(context)),
            schema=LeadScore,
        )

        contact.ai_score = result.score
        contact.ai_summary = result.reasoning
        contact.ai_scored_at = utc_now()
        await self.session.commit()
        return result

    async def draft_email(self, data: EmailDraftRequest) -> EmailDraft:
        contact = await self._get_contact(data.contact_id)
        context: dict[str, Any] = {"contact": _contact_data(contact)}
        if data.deal_id:
            context["deal"] = _deal_data(await self._get_deal(data.deal_id))
        context["recent_activities"] = [
            _activity_data(a)
            for a in await self.activities.list_recent(limit=5, contact_id=contact.id)
        ]
        return await self.ai.complete_json(
            system=prompts.EMAIL_DRAFT_SYSTEM,
            user=prompts.EMAIL_DRAFT_USER.format(
                purpose=data.purpose, tone=data.tone, context=_to_json(context)
            ),
            schema=EmailDraft,
            temperature=0.7,
        )

    async def summarize(self, data: SummarizeRequest) -> TimelineSummary:
        context: dict[str, Any] = {}
        if data.contact_id:
            context["contact"] = _contact_data(await self._get_contact(data.contact_id))
        if data.deal_id:
            context["deal"] = _deal_data(await self._get_deal(data.deal_id))
        activities = await self.activities.list_recent(
            limit=MAX_ACTIVITIES, contact_id=data.contact_id, deal_id=data.deal_id
        )
        context["activities"] = [_activity_data(a) for a in activities]
        return await self.ai.complete_json(
            system=prompts.SUMMARY_SYSTEM,
            user=prompts.SUMMARY_USER.format(context=_to_json(context)),
            schema=TimelineSummary,
        )

    async def extract_contact(self, data: ExtractContactRequest) -> ExtractedContact:
        return await self.ai.complete_json(
            system=prompts.EXTRACT_CONTACT_SYSTEM,
            user=prompts.EXTRACT_CONTACT_USER.format(text=data.text),
            schema=ExtractedContact,
            temperature=0.0,
        )

    async def capture_contact(self, text: str) -> CapturedContact:
        """Smart capture from a file: `text` was already read from it (OCR, PDF, ...)."""
        extracted = await self.extract_contact(ExtractContactRequest(text=text))
        return CapturedContact(**extracted.model_dump(), source_text=text)

    async def _get_contact(self, contact_id: uuid.UUID) -> Contact:
        contact = await self.contacts.get(contact_id)
        if contact is None:
            raise NotFoundError("Contact not found")
        return contact

    async def _get_deal(self, deal_id: uuid.UUID) -> Deal:
        deal = await self.deals.get(deal_id)
        if deal is None:
            raise NotFoundError("Deal not found")
        return deal


# --- Context helpers: plain dicts with only what the model needs ---


def _to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, default=str, ensure_ascii=False, indent=2)


def _contact_data(contact: Contact) -> dict[str, Any]:
    return {
        "name": f"{contact.first_name} {contact.last_name or ''}".strip(),
        "email": contact.email,
        "job_title": contact.job_title,
        "status": contact.status,
        "source": contact.source,
        "tags": contact.tags,
        "company": contact.company.name if contact.company else None,
        "created_at": contact.created_at,
    }


def _deal_data(deal: Deal) -> dict[str, Any]:
    return {
        "title": deal.title,
        "value": float(deal.value),
        "currency": deal.currency,
        "stage": deal.stage.name,
        "expected_close_date": deal.expected_close_date,
    }


def _activity_data(activity: Activity) -> dict[str, Any]:
    body = activity.body or ""
    return {
        "type": activity.type,
        "subject": activity.subject,
        "body": body[:MAX_BODY_CHARS],
        "occurred_at": activity.occurred_at,
    }
