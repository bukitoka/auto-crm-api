import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.companies.models import Company
from app.modules.companies.schemas import CompanyFilters
from app.shared.sorting import sort_by
from app.shared.utils import like_pattern

_LOAD_RELATED = (joinedload(Company.owner),)
_SORT_COLUMNS = {
    "name": func.lower(Company.name),
    "industry": func.lower(Company.industry),
    "created_at": Company.created_at,
}


class CompanyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, company_id: uuid.UUID) -> Company | None:
        query = (
            select(Company)
            .where(Company.id == company_id)
            .options(*_LOAD_RELATED)
            .execution_options(populate_existing=True)  # always reload fresh relations
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def exists(self, company_id: uuid.UUID) -> bool:
        return await self.session.get(Company, company_id) is not None

    async def get_by_name(self, name: str) -> Company | None:
        result = await self.session.execute(
            select(Company).where(func.lower(Company.name) == name.lower()).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_page(
        self, filters: CompanyFilters, *, offset: int, limit: int
    ) -> tuple[list[Company], int]:
        query = _filtered(filters)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            _sorted(query, filters).options(*_LOAD_RELATED).offset(offset).limit(limit)
        )
        return list(result.scalars()), total or 0

    async def list_all(self, filters: CompanyFilters) -> list[Company]:
        """Every matching company, in list order (for CSV export)."""
        query = _sorted(_filtered(filters), filters).options(*_LOAD_RELATED)
        return list((await self.session.execute(query)).scalars())

    async def add(self, company: Company) -> Company:
        self.session.add(company)
        await self.session.flush()
        return company

    async def delete(self, company: Company) -> None:
        await self.session.delete(company)
        await self.session.flush()


def _filtered(filters: CompanyFilters) -> Select[Company]:
    query = select(Company)
    if filters.search:
        pattern = like_pattern(filters.search)
        query = query.where(or_(Company.name.ilike(pattern), Company.domain.ilike(pattern)))
    if filters.industry:
        query = query.where(Company.industry == filters.industry)
    return query


def _sorted(query: Select[Company], filters: CompanyFilters) -> Select[Company]:
    if filters.sort is None:
        return query.order_by(Company.name)
    return query.order_by(sort_by(_SORT_COLUMNS[filters.sort], filters.order), Company.id)
