import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.activities.models import Activity
from app.modules.activities.repository import ActivityRepository
from app.modules.activities.schemas import ActivityCreate, ActivityFilters, ActivityRead
from app.modules.contacts.repository import ContactRepository
from app.modules.deals.repository import DealRepository
from app.modules.users.models import User
from app.shared.pagination import Page, PageParams
from app.shared.utils import utc_now


class ActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ActivityRepository(session)
        self.contacts = ContactRepository(session)
        self.deals = DealRepository(session)

    async def get(self, activity_id: uuid.UUID) -> Activity:
        activity = await self.repo.get(activity_id)
        if activity is None:
            raise NotFoundError("Activity not found")
        return activity

    async def list_page(self, filters: ActivityFilters, params: PageParams) -> Page[ActivityRead]:
        items, total = await self.repo.list_page(filters, offset=params.offset, limit=params.size)
        return Page[ActivityRead].from_items(items, total, params)

    async def create(self, data: ActivityCreate, *, user: User) -> Activity:
        if data.contact_id and not await self.contacts.exists(data.contact_id):
            raise NotFoundError("Contact not found")
        if data.deal_id and not await self.deals.exists(data.deal_id):
            raise NotFoundError("Deal not found")

        activity = Activity(**data.model_dump())
        activity.occurred_at = data.occurred_at or utc_now()
        activity.created_by_id = user.id
        await self.repo.add(activity)
        await self.session.commit()
        return await self.get(activity.id)

    async def delete(self, activity_id: uuid.UUID) -> None:
        activity = await self.get(activity_id)
        await self.repo.delete(activity)
        await self.session.commit()
