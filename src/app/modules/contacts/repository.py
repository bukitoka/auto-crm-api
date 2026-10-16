import uuid

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.companies.models import Company
from app.modules.contacts.models import Contact, ContactStatus
from app.modules.contacts.schemas import ContactFilters
from app.shared.sorting import sort_by
from app.shared.utils import like_pattern

_LOAD_RELATED = (joinedload(Contact.company), joinedload(Contact.owner))
_FULL_NAME = Contact.first_name + " " + func.coalesce(Contact.last_name, "")
_STATUS_ORDER = {status: index for index, status in enumerate(ContactStatus)}  # lifecycle order
_SORT_COLUMNS = {
    "name": func.lower(_FULL_NAME),
    "email": Contact.email,
    "status": case(_STATUS_ORDER, value=Contact.status),
    "company": func.lower(Company.name),
    "ai_score": Contact.ai_score,
    "created_at": Contact.created_at,
}


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
        query = _filtered(filters)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            _sorted(query, filters).options(*_LOAD_RELATED).offset(offset).limit(limit)
        )
        return list(result.scalars()), total or 0

    async def list_all(self, filters: ContactFilters) -> list[Contact]:
        """Every matching contact, in list order (for CSV export)."""
        result = await self.session.execute(
            _sorted(_filtered(filters), filters).options(*_LOAD_RELATED)
        )
        return list(result.scalars())

    async def add(self, contact: Contact) -> Contact:
        self.session.add(contact)
        await self.session.flush()
        return contact

    async def delete(self, contact: Contact) -> None:
        await self.session.delete(contact)
        await self.session.flush()


def _filtered(filters: ContactFilters) -> Select[Contact]:
    query = select(Contact)
    if filters.search:
        pattern = like_pattern(filters.search)
        query = query.where(
            or_(
                _FULL_NAME.ilike(pattern),
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
    return query


def _sorted(query: Select[Contact], filters: ContactFilters) -> Select[Contact]:
    if filters.sort is None:
        return query.order_by(Contact.created_at.desc())
    if filters.sort == "company":
        query = query.outerjoin(Company, Contact.company_id == Company.id)
    return query.order_by(sort_by(_SORT_COLUMNS[filters.sort], filters.order), Contact.id)
