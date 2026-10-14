import uuid

from sqlalchemy import ColumnElement, and_, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.tasks.models import Task, TaskStatus
from app.modules.tasks.schemas import TaskFilters
from app.shared.utils import like_pattern, today_utc

_LOAD_RELATED = (
    joinedload(Task.assignee),
    joinedload(Task.created_by),
    joinedload(Task.contact),
    joinedload(Task.deal),
)


def _is_overdue() -> ColumnElement[bool]:
    # `is_not(None)` keeps the result true/false (never NULL), so `not_(...)` also
    # matches tasks without a due date when filtering with overdue=false.
    return and_(
        Task.due_date.is_not(None), Task.due_date < today_utc(), Task.status != TaskStatus.DONE
    )


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, task_id: uuid.UUID) -> Task | None:
        query = (
            select(Task)
            .where(Task.id == task_id)
            .options(*_LOAD_RELATED)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_page(
        self, filters: TaskFilters, *, offset: int, limit: int
    ) -> tuple[list[Task], int]:
        query = select(Task)
        if filters.search:
            query = query.where(Task.title.ilike(like_pattern(filters.search)))
        if filters.status:
            query = query.where(Task.status == filters.status)
        if filters.assignee_id:
            query = query.where(Task.assignee_id == filters.assignee_id)
        if filters.contact_id:
            query = query.where(Task.contact_id == filters.contact_id)
        if filters.deal_id:
            query = query.where(Task.deal_id == filters.deal_id)
        if filters.overdue is True:
            query = query.where(_is_overdue())
        elif filters.overdue is False:
            query = query.where(not_(_is_overdue()))

        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            query.options(*_LOAD_RELATED)
            .order_by(Task.due_date.asc().nulls_last(), Task.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars()), total or 0

    async def list_open_for_assignee(self, assignee_id: uuid.UUID, limit: int) -> list[Task]:
        result = await self.session.execute(
            select(Task)
            .where(Task.assignee_id == assignee_id, Task.status != TaskStatus.DONE)
            .options(*_LOAD_RELATED)
            .order_by(Task.due_date.asc().nulls_last(), Task.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def count_overdue(self) -> int:
        result = await self.session.scalar(
            select(func.count()).select_from(Task).where(_is_overdue())
        )
        return result or 0

    async def add(self, task: Task) -> Task:
        self.session.add(task)
        await self.session.flush()
        return task

    async def delete(self, task: Task) -> None:
        await self.session.delete(task)
        await self.session.flush()
