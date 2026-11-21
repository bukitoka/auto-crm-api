import uuid
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activities.models import Activity, ActivityType
from app.modules.contacts.models import Contact, ContactStatus
from app.modules.deals.models import Deal
from app.modules.integrations.models import LeadRouting
from app.modules.tasks.models import Task, TaskStatus
from app.shared.utils import today_utc, utc_now


class FollowUp(BaseModel):
    kind: Literal["task", "deal", "lead"]
    id: uuid.UUID
    title: str
    due_date: date | None = None
    contact_id: uuid.UUID | None = None
    response_due_at: datetime | None = None
    response_overdue: bool = False


async def list_follow_ups(session: AsyncSession) -> list[FollowUp]:
    today = today_utc()
    now = utc_now()
    routing = await session.get(LeadRouting, 1)
    response_window = timedelta(hours=routing.response_hours if routing else 24)
    open_task = Task.status != TaskStatus.DONE
    tasks = await session.scalars(
        select(Task)
        .where(open_task, Task.due_date < today)
        .order_by(Task.due_date, Task.id)
        .limit(30)
    )
    next_step = (
        select(Task.id).where(Task.deal_id == Deal.id, open_task, Task.due_date >= today).exists()
    )
    deals = await session.scalars(
        select(Deal)
        .where(
            Deal.closed_at.is_(None),
            Deal.expected_close_date <= today + timedelta(days=14),
            ~next_step,
        )
        .order_by(Deal.expected_close_date, Deal.id)
        .limit(30)
    )
    contacted = (
        select(Activity.id)
        .where(
            Activity.contact_id == Contact.id,
            Activity.type.in_([ActivityType.CALL, ActivityType.EMAIL, ActivityType.MEETING]),
        )
        .exists()
    )
    leads = await session.scalars(
        select(Contact)
        .where(Contact.status == ContactStatus.LEAD, ~contacted)
        .order_by(Contact.created_at, Contact.id)
        .limit(30)
    )
    return [
        *(
            FollowUp(
                kind="task", id=t.id, title=t.title, due_date=t.due_date, contact_id=t.contact_id
            )
            for t in tasks
        ),
        *(
            FollowUp(
                kind="deal",
                id=d.id,
                title=d.title,
                due_date=d.expected_close_date,
                contact_id=d.contact_id,
            )
            for d in deals
        ),
        *(
            FollowUp(
                kind="lead",
                id=c.id,
                title=" ".join(filter(None, [c.first_name, c.last_name])),
                contact_id=c.id,
                response_due_at=c.created_at + response_window,
                response_overdue=c.created_at + response_window <= now,
            )
            for c in leads
        ),
    ]
