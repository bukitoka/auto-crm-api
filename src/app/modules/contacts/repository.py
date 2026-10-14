import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.contacts.models import Contact
from app.modules.contacts.schemas import ContactFilters
from app.shared.utils import like_pattern

_LOAD_RELATED = (joinedload(Contact.company), joinedload(Contact.owner))


class ContactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, contact_id: uuid.UUID) -> Contact | None:
        query = (
            select(Contact)
            .where(Contact.id == contact_id)
            .options(*_LOAD_RELATED)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def exists(self, contact_id: uuid.UUID) -> bool:
        return await self.session.get(Contact, contact_id) is not None

    async def get_by_email(self, email: str) -> Contact | None:
        result = await self.session.execute(select(Contact).where(Contact.email == email.lower()))
        return result.scalar_one_or_none()

    async def list_page(
        self, filters: ContactFilters, *, offset: int, limit: int
    ) -> tuple[list[Contact], int]:
        query = select(Contact)
        if filters.search:
            pattern = like_pattern(filters.search)
            full_name = Contact.first_name + " " + func.coalesce(Contact.last_name, "")
            query = query.where(
                or_(
                    full_name.ilike(pattern),
                    Contact.email.ilike(pattern),
                    Contact.phone.ilike(pattern),
                )
            )
        if filters.status:
            query = query.where(Contact.status == filters.status)
        if filters.company_id:
            query = query.where(Contact.company_id == filters.company_id)
        if filters.owner_id:
            query = query.where(Contact.owner_id == filters.owner_id)

        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            query.options(*_LOAD_RELATED)
            .order_by(Contact.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars()), total or 0

    async def add(self, contact: Contact) -> Contact:
        self.session.add(contact)
        await self.session.flush()
        return contact

    async def delete(self, contact: Contact) -> None:
        await self.session.delete(contact)
        await self.session.flush()
