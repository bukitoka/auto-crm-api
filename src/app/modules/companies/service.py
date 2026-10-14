import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.storage import Storage, get_storage
from app.modules.companies.models import Company
from app.modules.companies.repository import CompanyRepository
from app.modules.companies.schemas import (
    CompanyCreate,
    CompanyFilters,
    CompanyRead,
    CompanyUpdate,
)
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.shared.images import replace_image
from app.shared.pagination import Page, PageParams


class CompanyService:
    def __init__(self, session: AsyncSession, storage: Storage | None = None) -> None:
        self.session = session
        self.storage = storage or get_storage()
        self.repo = CompanyRepository(session)
        self.users = UserRepository(session)

    async def get(self, company_id: uuid.UUID) -> Company:
        company = await self.repo.get(company_id)
        if company is None:
            raise NotFoundError("Company not found")
        return company

    async def list_page(self, filters: CompanyFilters, params: PageParams) -> Page[CompanyRead]:
        items, total = await self.repo.list_page(filters, offset=params.offset, limit=params.size)
        return Page[CompanyRead].from_items(items, total, params)

    async def create(self, data: CompanyCreate, *, user: User) -> Company:
        await self._check_owner(data.owner_id)
        company = Company(**data.model_dump())
        company.owner_id = data.owner_id or user.id
        await self.repo.add(company)
        await self.session.commit()
        return await self.get(company.id)

    async def update(self, company_id: uuid.UUID, data: CompanyUpdate) -> Company:
        company = await self.get(company_id)
        changes = data.model_dump(exclude_unset=True)
        await self._check_owner(changes.get("owner_id"))
        for field, value in changes.items():
            setattr(company, field, value)
        await self.session.commit()
        return await self.get(company.id)

    async def delete(self, company_id: uuid.UUID) -> None:
        company = await self.get(company_id)
        await self.repo.delete(company)
        await self.session.commit()
        if company.logo_key:
            await self.storage.delete(company.logo_key)

    async def set_logo(self, company_id: uuid.UUID, image: bytes) -> Company:
        """Store a new logo (already converted by `read_image`) for the company."""
        company = await self.get(company_id)
        company.logo_key = await replace_image(
            self.storage, folder=f"companies/{company.id}", image=image, old_key=company.logo_key
        )
        await self.session.commit()
        return await self.get(company.id)

    async def remove_logo(self, company_id: uuid.UUID) -> Company:
        company = await self.get(company_id)
        if company.logo_key:
            old_key, company.logo_key = company.logo_key, None
            await self.session.commit()
            await self.storage.delete(old_key)
        return await self.get(company.id)

    async def _check_owner(self, owner_id: uuid.UUID | None) -> None:
        if owner_id is not None and await self.users.get(owner_id) is None:
            raise NotFoundError("Owner not found")
