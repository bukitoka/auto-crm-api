import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.companies.models import Company
from app.modules.companies.schemas import CompanyFilters
from app.shared.utils import like_pattern

_LOAD_RELATED = (joinedload(Company.owner),)


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
        query = select(Company)
        if filters.search:
            pattern = like_pattern(filters.search)
            query = query.where(or_(Company.name.ilike(pattern), Company.domain.ilike(pattern)))
        if filters.industry:
            query = query.where(Company.industry == filters.industry)

        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            query.options(*_LOAD_RELATED).order_by(Company.name).offset(offset).limit(limit)
        )
        return list(result.scalars()), total or 0

    async def add(self, company: Company) -> Company:
        self.session.add(company)
        await self.session.flush()
        return company

    async def delete(self, company: Company) -> None:
        await self.session.delete(company)
        await self.session.flush()
