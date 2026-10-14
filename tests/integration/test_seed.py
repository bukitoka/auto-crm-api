from collections import Counter

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app import seed
from app.core.database import SessionFactory
from app.modules.activities.models import Activity
from app.modules.companies.models import Company
from app.modules.contacts.models import Contact
from app.modules.deals.models import Deal
from app.modules.tasks.models import Task, TaskStatus
from app.modules.users.models import User, UserRole
from app.modules.webhooks.models import WebhookSubscription
from app.shared.utils import today_utc


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
async def seeded() -> None:
    assert await seed.seed(reset=False) == 0


async def test_seed_creates_the_expected_number_of_records(seeded: None) -> None:
    async with SessionFactory() as session:
        assert await _count(session, User) == 1 + len(seed.MEMBERS)
        assert await _count(session, Company) == seed.COMPANY_COUNT
        assert await _count(session, Contact) == seed.CONTACT_COUNT
        assert await _count(session, Deal) == seed.DEAL_COUNT
        assert await _count(session, Activity) == seed.ACTIVITY_COUNT
        assert await _count(session, Task) == seed.TASK_COUNT
        assert await _count(session, WebhookSubscription) == len(seed.N8N_WEBHOOKS)


async def test_seeded_users_follow_the_first_user_is_admin_rule(seeded: None) -> None:
    async with SessionFactory() as session:
        rows = (await session.execute(select(User.email, User.role))).all()
        roles = {email: role for email, role in rows}

    assert roles[seed.ADMIN[0]] == UserRole.ADMIN
    assert [roles[email] for email, _, _ in seed.MEMBERS] == [UserRole.MEMBER] * 3


async def test_seeded_contacts_and_activities_cover_every_option(seeded: None) -> None:
    async with SessionFactory() as session:
        statuses = set((await session.scalars(select(Contact.status))).all())
        activity_types = set((await session.scalars(select(Activity.type))).all())
        tagged = await session.scalar(
            select(func.count()).select_from(Contact).where(func.cardinality(Contact.tags) > 0)
        )

    assert statuses == {"lead", "prospect", "customer", "churned"}
    assert activity_types == {"note", "call", "email", "meeting"}
    assert tagged


async def test_seeded_deals_respect_closed_at_rules(seeded: None) -> None:
    async with SessionFactory() as session:
        deals = (await session.scalars(select(Deal).options(joinedload(Deal.stage)))).all()

    per_stage = Counter(deal.stage.name for deal in deals)
    assert set(per_stage) == {"Qualification", "Proposal", "Negotiation", "Won", "Lost"}
    for deal in deals:
        is_closed = deal.stage.is_won or deal.stage.is_lost
        assert (deal.closed_at is not None) == is_closed, deal.title
        if deal.closed_at:
            assert deal.closed_at >= deal.created_at


async def test_seeded_tasks_include_overdue_and_done(seeded: None) -> None:
    async with SessionFactory() as session:
        tasks = (await session.scalars(select(Task))).all()

    overdue = [
        t for t in tasks if t.due_date and t.due_date < today_utc() and t.status != TaskStatus.DONE
    ]
    done = [t for t in tasks if t.status == TaskStatus.DONE]
    assert len(overdue) >= 5
    assert done
    assert all(t.completed_at is not None for t in done)
    assert all(t.completed_at is None for t in tasks if t.status != TaskStatus.DONE)


async def test_seeded_webhooks_are_inactive(seeded: None) -> None:
    async with SessionFactory() as session:
        webhooks = (await session.scalars(select(WebhookSubscription))).all()

    assert {w.target_url for w in webhooks} == {url for _, url in seed.N8N_WEBHOOKS}
    assert not any(w.is_active for w in webhooks)


async def test_seed_refuses_to_run_twice_without_reset(seeded: None) -> None:
    assert await seed.seed(reset=False) == 1


async def test_seed_with_reset_replaces_the_data(seeded: None) -> None:
    assert await seed.seed(reset=True) == 0

    async with SessionFactory() as session:
        assert await _count(session, Contact) == seed.CONTACT_COUNT


async def test_seed_ignores_the_service_account(client, api_key_headers) -> None:
    await client.get("/api/v1/auth/me", headers=api_key_headers)  # creates the service account

    assert await seed.seed(reset=False) == 0
