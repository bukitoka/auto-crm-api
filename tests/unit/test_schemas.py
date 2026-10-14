"""Request/response schema rules (validation happens before any service code runs)."""

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.activities.schemas import ActivityCreate
from app.modules.ai.schemas import LeadScore, SummarizeRequest
from app.modules.auth.schemas import RegisterRequest
from app.modules.companies.schemas import CompanyUpdate
from app.modules.contacts.models import ContactStatus
from app.modules.contacts.schemas import ContactCreate, ContactUpdate
from app.modules.deals.schemas import DealCreate, DealRead, DealUpdate
from app.modules.tasks.schemas import TaskUpdate
from app.modules.webhooks.schemas import WebhookCreate, WebhookUpdate
from tests.unit.conftest import make_deal

# --- PATCH rules: omitted = unchanged, null clears optional fields, null on required = 422 ---


@pytest.mark.parametrize(
    ("schema", "field"),
    [
        (ContactUpdate, "first_name"),
        (ContactUpdate, "status"),
        (ContactUpdate, "tags"),
        (CompanyUpdate, "name"),
        (DealUpdate, "title"),
        (DealUpdate, "value"),
        (DealUpdate, "stage_id"),
        (TaskUpdate, "title"),
        (TaskUpdate, "status"),
        (WebhookUpdate, "is_active"),
    ],
)
def test_patch_rejects_null_for_required_fields(schema: type, field: str) -> None:
    with pytest.raises(ValidationError, match="may not be null"):
        schema.model_validate({field: None})


def test_patch_accepts_null_for_optional_fields() -> None:
    update = ContactUpdate.model_validate({"last_name": None, "company_id": None})

    assert update.model_dump(exclude_unset=True) == {"last_name": None, "company_id": None}


def test_patch_leaves_omitted_fields_unset() -> None:
    update = DealUpdate.model_validate({"title": "Renamed"})

    assert update.model_dump(exclude_unset=True) == {"title": "Renamed"}


# --- Contacts ---


def test_contact_create_defaults() -> None:
    contact = ContactCreate(first_name="Jane")

    assert contact.status == ContactStatus.LEAD
    assert contact.source == "manual"
    assert contact.tags == []


def test_contact_create_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        ContactCreate.model_validate({"first_name": "Jane", "email": "not-an-email"})


def test_contact_create_requires_a_first_name() -> None:
    with pytest.raises(ValidationError):
        ContactCreate.model_validate({"first_name": ""})


# --- Deals ---


def test_deal_value_accepts_a_numeric_string() -> None:
    deal = DealCreate.model_validate({"title": "Deal", "value": "1234.50"})

    assert deal.value == Decimal("1234.50")


@pytest.mark.parametrize("value", ["-1", "1.234", "abc"])
def test_deal_value_rejects_invalid_amounts(value: str) -> None:
    with pytest.raises(ValidationError):
        DealCreate.model_validate({"title": "Deal", "value": value})


def test_deal_create_defaults() -> None:
    deal = DealCreate(title="Deal")

    assert deal.value == 0
    assert deal.currency == "USD"
    assert deal.stage_id is None


def test_deal_read_serializes_value_as_a_number() -> None:
    data = DealRead.model_validate(make_deal(value=Decimal("99.90"))).model_dump(mode="json")

    assert data["value"] == 99.9


# --- Activities / AI requests ---


def test_activity_requires_a_contact_or_a_deal() -> None:
    with pytest.raises(ValidationError, match="contact_id and/or a deal_id"):
        ActivityCreate.model_validate({"type": "note", "subject": "Hi"})


@pytest.mark.parametrize("target", ["contact_id", "deal_id"])
def test_activity_accepts_either_target(target: str) -> None:
    activity = ActivityCreate.model_validate(
        {"type": "call", "subject": "Hi", target: uuid.uuid7()}
    )

    assert getattr(activity, target) is not None


def test_summarize_request_requires_a_contact_or_a_deal() -> None:
    with pytest.raises(ValidationError, match="contact_id and/or a deal_id"):
        SummarizeRequest()


@pytest.mark.parametrize("score", [-1, 101])
def test_lead_score_must_be_between_0_and_100(score: int) -> None:
    with pytest.raises(ValidationError):
        LeadScore(score=score, reasoning="x")


# --- Auth / webhooks ---


def test_register_requires_a_password_of_at_least_8_characters() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest.model_validate(
            {"email": "a@example.com", "password": "short", "full_name": "A"}
        )


def test_webhook_rejects_unknown_events_and_bad_urls() -> None:
    with pytest.raises(ValidationError):
        WebhookCreate.model_validate({"event": "deal.exploded", "target_url": "http://x.io"})
    with pytest.raises(ValidationError):
        WebhookCreate.model_validate({"event": "deal.won", "target_url": "not a url"})
