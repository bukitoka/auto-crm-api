"""Unit test helpers: no database, no network.

Services are built with a mocked `AsyncSession`; tests then swap the repositories the
service created for `AsyncMock`s (see `mock_repos`). The `make_*` factories build
in-memory ORM objects with every field a response schema needs.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.events import Event
from app.modules.activities.models import Activity, ActivityType
from app.modules.companies.models import Company
from app.modules.contacts.models import Contact, ContactStatus
from app.modules.deals.models import Deal
from app.modules.pipeline.models import PipelineStage
from app.modules.tasks.models import Task, TaskPriority, TaskStatus
from app.modules.users.models import User, UserRole
from app.modules.webhooks.models import WebhookSubscription

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def session() -> AsyncMock:
    """A stand-in for AsyncSession: `commit`, `refresh`, ... are AsyncMocks."""
    mock = AsyncMock(spec=AsyncSession)
    mock.sync_session = MagicMock(info={})
    return mock


@pytest.fixture
def published_events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Event, dict[str, Any]]]:
    """Records `events.publish(...)` calls instead of starting background handlers."""
    received: list[tuple[Event, dict[str, Any]]] = []
    monkeypatch.setattr(events, "publish", lambda event, data: received.append((event, data)))
    return received


def mock_repos(service: Any, *names: str) -> None:
    """Replace the named repository attributes of a service with AsyncMocks."""
    for name in names:
        repo = AsyncMock()
        repo.add = AsyncMock(side_effect=lambda obj: obj)  # like the real add(): returns obj
        setattr(service, name, repo)


def event_names(published: list[tuple[Event, dict[str, Any]]]) -> list[Event]:
    return [event for event, _ in published]


def make_user(**overrides: Any) -> User:
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "email": "user@example.com",
        "hashed_password": "not-a-real-hash",
        "full_name": "Uma User",
        "role": UserRole.ADMIN,
        "is_active": True,
        "is_super_admin": False,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return User(**(values | overrides))


def make_company(**overrides: Any) -> Company:
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "name": "Acme Inc",
        "domain": "acme.com",
        "industry": "Software",
        "size": None,
        "website": None,
        "notes": None,
        "owner_id": None,
        "owner": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return Company(**(values | overrides))


def make_contact(**overrides: Any) -> Contact:
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane@acme.com",
        "phone": None,
        "job_title": "CTO",
        "status": ContactStatus.LEAD,
        "source": "manual",
        "tags": [],
        "company_id": None,
        "company": None,
        "owner_id": None,
        "owner": None,
        "ai_score": None,
        "ai_summary": None,
        "ai_scored_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return Contact(**(values | overrides))


def make_stage(name: str = "Qualification", **overrides: Any) -> PipelineStage:
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "name": name,
        "position": 1,
        "probability": 10,
        "is_won": name == "Won",
        "is_lost": name == "Lost",
    }
    return PipelineStage(**(values | overrides))


def make_deal(stage: PipelineStage | None = None, **overrides: Any) -> Deal:
    stage = stage or make_stage()
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "title": "Big deal",
        "value": Decimal("1000.00"),
        "currency": "USD",
        "stage_id": stage.id,
        "stage": stage,
        "contact_id": None,
        "contact": None,
        "company_id": None,
        "company": None,
        "owner_id": None,
        "owner": None,
        "expected_close_date": None,
        "closed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return Deal(**(values | overrides))


def make_activity(**overrides: Any) -> Activity:
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "type": ActivityType.CALL,
        "subject": "Discovery call",
        "body": "Talked about pricing.",
        "occurred_at": NOW,
        "contact_id": None,
        "contact": None,
        "deal_id": None,
        "deal": None,
        "created_by_id": None,
        "created_by": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return Activity(**(values | overrides))


def make_task(**overrides: Any) -> Task:
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "title": "Send proposal",
        "description": None,
        "due_date": date(2026, 1, 20),
        "priority": TaskPriority.MEDIUM,
        "status": TaskStatus.TODO,
        "completed_at": None,
        "assignee_id": None,
        "assignee": None,
        "contact_id": None,
        "contact": None,
        "deal_id": None,
        "deal": None,
        "created_by_id": None,
        "created_by": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return Task(**(values | overrides))


def make_webhook(**overrides: Any) -> WebhookSubscription:
    values: dict[str, Any] = {
        "id": uuid.uuid7(),
        "event": Event.DEAL_WON,
        "target_url": "http://n8n.local/hook",
        "secret": "top-secret",
        "is_active": True,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return WebhookSubscription(**(values | overrides))
