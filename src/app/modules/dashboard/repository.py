import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Row, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.activities.models import Activity
from app.modules.contacts.models import Contact
from app.modules.deals.models import Deal
from app.modules.pipeline.models import PipelineStage
from app.modules.tasks.models import Task, TaskStatus
from app.modules.users.models import User
from app.modules.users.service import SERVICE_ACCOUNT_EMAIL

_IS_OPEN_STAGE = and_(PipelineStage.is_won.is_(False), PipelineStage.is_lost.is_(False))
_IS_OPEN_TASK = Task.status != TaskStatus.DONE


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def open_pipeline_value(self) -> Decimal:
        result = await self.session.scalar(
            select(func.coalesce(func.sum(Deal.value), 0)).join(Deal.stage).where(_IS_OPEN_STAGE)
        )
        return Decimal(result or 0)

    async def closed_deals_since(self, since: datetime) -> Row:
        """(won_count, lost_count, won_value) of deals closed at or after `since`."""
        result = await self.session.execute(
            select(
                func.count().filter(PipelineStage.is_won.is_(True)).label("won_count"),
                func.count().filter(PipelineStage.is_lost.is_(True)).label("lost_count"),
                func.coalesce(func.sum(Deal.value).filter(PipelineStage.is_won.is_(True)), 0).label(
                    "won_value"
                ),
            )
            .join(Deal.stage)
            .where(Deal.closed_at >= since)
        )
        return result.one()

    async def contacts_created_since(self, since: datetime) -> int:
        result = await self.session.scalar(
            select(func.count()).select_from(Contact).where(Contact.created_at >= since)
        )
        return result or 0

    async def contacts_by_status(self) -> dict[str, int]:
        result = await self.session.execute(
            select(Contact.status, func.count()).group_by(Contact.status)
        )
        return {status: count for status, count in result.all()}

    async def activities_by_type_since(self, since: datetime) -> dict[str, int]:
        result = await self.session.execute(
            select(Activity.type, func.count())
            .where(Activity.occurred_at >= since)
            .group_by(Activity.type)
        )
        return {type_: count for type_, count in result.all()}

    async def open_tasks_due_between(self, start: date, end: date) -> int:
        result = await self.session.scalar(
            select(func.count())
            .select_from(Task)
            .where(_IS_OPEN_TASK, Task.due_date >= start, Task.due_date <= end)
        )
        return result or 0

    async def overdue_tasks(self, today: date, limit: int) -> list[Task]:
        """Everyone's open tasks due before `today`, oldest first."""
        result = await self.session.execute(
            select(Task)
            .where(_IS_OPEN_TASK, Task.due_date < today)
            .options(
                joinedload(Task.assignee),
                joinedload(Task.created_by),
                joinedload(Task.contact),
                joinedload(Task.deal),
            )
            .order_by(Task.due_date, Task.created_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def open_deals_closing_between(self, start: date, end: date, limit: int) -> list[Deal]:
        result = await self.session.execute(
            select(Deal)
            .join(Deal.stage)
            .where(_IS_OPEN_STAGE, Deal.expected_close_date.between(start, end))
            .options(
                joinedload(Deal.stage),
                joinedload(Deal.contact),
                joinedload(Deal.company),
                joinedload(Deal.owner),
            )
            .order_by(Deal.expected_close_date, Deal.value.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def leaderboard(
        self, month_start: datetime, *, only_id: uuid.UUID | None = None
    ) -> list[Row]:
        """Per active admin (or just `only_id`): (User, open value, won this month, open tasks)."""
        deals = (
            select(
                Deal.owner_id,
                func.sum(case((_IS_OPEN_STAGE, Deal.value), else_=0)).label("open_value"),
                func.sum(
                    case(
                        (and_(PipelineStage.is_won, Deal.closed_at >= month_start), Deal.value),
                        else_=0,
                    )
                ).label("won_value"),
            )
            .join(Deal.stage)
            .group_by(Deal.owner_id)
            .subquery()
        )
        tasks = (
            select(Task.assignee_id, func.count().label("open_tasks"))
            .where(_IS_OPEN_TASK)
            .group_by(Task.assignee_id)
            .subquery()
        )
        won_value = func.coalesce(deals.c.won_value, 0).label("won_this_month_value")
        open_value = func.coalesce(deals.c.open_value, 0).label("open_deals_value")
        people = (
            select(
                User,
                open_value,
                won_value,
                func.coalesce(tasks.c.open_tasks, 0).label("open_tasks"),
            )
            .outerjoin(deals, deals.c.owner_id == User.id)
            .outerjoin(tasks, tasks.c.assignee_id == User.id)
            .where(
                User.is_active.is_(True),
                User.is_super_admin.is_(False),
                User.email != SERVICE_ACCOUNT_EMAIL,
            )
            .order_by(won_value.desc(), open_value.desc(), User.full_name)
        )
        if only_id is not None:
            people = people.where(User.id == only_id)
        result = await self.session.execute(people)
        return list(result.all())

    async def pipeline_by_stage(self) -> list[Row]:
        """One row per stage: (stage_id, stage_name, deal_count, total_value)."""
        query = (
            select(
                PipelineStage.id.label("stage_id"),
                PipelineStage.name.label("stage_name"),
                func.count(Deal.id).label("deal_count"),
                func.coalesce(func.sum(Deal.value), 0).label("total_value"),
            )
            .outerjoin(Deal, Deal.stage_id == PipelineStage.id)
            .group_by(PipelineStage.id)
            .order_by(PipelineStage.position)
        )
        result = await self.session.execute(query)
        return list(result.all())
