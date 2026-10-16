import uuid

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import ensure_own
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
from app.shared.csv_files import ImportResult, to_csv, validation_message
from app.shared.images import replace_image
from app.shared.pagination import Page, PageParams

# CSV columns: these map 1:1 to `CompanyCreate` fields, the rest are export-only.
_PLAIN_FIELDS = ["name", "domain", "industry", "size", "website", "notes"]
CSV_COLUMNS = [*_PLAIN_FIELDS, "owner", "created_at"]


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

    async def export_csv(self, filters: CompanyFilters) -> str:
        companies = await self.repo.list_all(filters)
        return to_csv(
            CSV_COLUMNS,
            (
                [
                    *(getattr(company, field) for field in _PLAIN_FIELDS),
                    company.owner.full_name if company.owner else None,
                    company.created_at.isoformat(),
                ]
                for company in companies
            ),
        )

    async def import_csv(
        self, rows: list[tuple[int, dict[str, str]]], *, user: User
    ) -> ImportResult:
        """Create a company per row; invalid rows and names that already exist are skipped."""
        result = ImportResult()
        for number, row in rows:
            try:
                data = CompanyCreate.model_validate({f: row[f] for f in _PLAIN_FIELDS if f in row})
            except ValidationError as exc:
                result.skip(number, validation_message(exc))
                continue
            if await self.repo.get_by_name(data.name) is not None:
                result.skip(number, "A company with this name already exists")
                continue
            await self.create(data, user=user)
            result.created += 1
        return result

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
        ensure_own(self.session, owner_id)
        if owner_id is not None and await self.users.get(owner_id) is None:
            raise NotFoundError("Owner not found")
