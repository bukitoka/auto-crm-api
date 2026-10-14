import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.activities.models import Activity
from app.modules.activities.schemas import ActivityFilters
from app.shared.utils import like_pattern

_LOAD_RELATED = (
    joinedload(Activity.contact),
    joinedload(Activity.deal),
    joinedload(Activity.created_by),
)


class ActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, activity_id: uuid.UUID) -> Activity | None:
        query = (
            select(Activity)
            .where(Activity.id == activity_id)
            .options(*_LOAD_RELATED)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_page(
        self, filters: ActivityFilters, *, offset: int, limit: int
    ) -> tuple[list[Activity], int]:
        query = select(Activity)
        if filters.search:
            pattern = like_pattern(filters.search)
            query = query.where(or_(Activity.subject.ilike(pattern), Activity.body.ilike(pattern)))
        if filters.contact_id:
            query = query.where(Activity.contact_id == filters.contact_id)
        if filters.deal_id:
            query = query.where(Activity.deal_id == filters.deal_id)
        if filters.type:
            query = query.where(Activity.type == filters.type)

        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            query.options(*_LOAD_RELATED)
            .order_by(Activity.occurred_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars()), total or 0

    async def list_recent(
        self,
        *,
        limit: int,
        contact_id: uuid.UUID | None = None,
        deal_id: uuid.UUID | None = None,
    ) -> list[Activity]:
        """Most recent activities, optionally for a contact and/or deal (matches either)."""
        query = select(Activity).options(*_LOAD_RELATED)
        conditions = []
        if contact_id:
            conditions.append(Activity.contact_id == contact_id)
        if deal_id:
            conditions.append(Activity.deal_id == deal_id)
        if conditions:
            query = query.where(or_(*conditions))
        result = await self.session.execute(
            query.order_by(Activity.occurred_at.desc()).limit(limit)
        )
        return list(result.scalars())

    async def add(self, activity: Activity) -> Activity:
        self.session.add(activity)
        await self.session.flush()
        return activity

    async def delete(self, activity: Activity) -> None:
        await self.session.delete(activity)
        await self.session.flush()
