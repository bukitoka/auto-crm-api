import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.deals.models import Deal
from app.modules.deals.schemas import DealFilters
from app.modules.pipeline.models import PipelineStage
from app.shared.sorting import sort_by
from app.shared.utils import like_pattern

_LOAD_RELATED = (
    joinedload(Deal.stage),
    joinedload(Deal.contact),
    joinedload(Deal.company),
    joinedload(Deal.owner),
)
_SORT_COLUMNS = {
    "title": func.lower(Deal.title),
    "value": Deal.value,
    "stage": PipelineStage.position,  # pipeline order
    "expected_close_date": Deal.expected_close_date,
    "created_at": Deal.created_at,
}


class DealRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, deal_id: uuid.UUID) -> Deal | None:
        query = (
            select(Deal)
            .where(Deal.id == deal_id)
            .options(*_LOAD_RELATED)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def exists(self, deal_id: uuid.UUID) -> bool:
        return await self.session.get(Deal, deal_id) is not None

    async def list_page(
        self, filters: DealFilters, *, offset: int, limit: int
    ) -> tuple[list[Deal], int]:
        query = _filtered(filters)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            _sorted(query, filters).options(*_LOAD_RELATED).offset(offset).limit(limit)
        )
        return list(result.scalars()), total or 0

    async def list_all(self, filters: DealFilters) -> list[Deal]:
        """Every matching deal, in list order (for CSV export)."""
        query = _sorted(_filtered(filters), filters).options(*_LOAD_RELATED)
        return list((await self.session.execute(query)).scalars())

    async def list_for_contact(self, contact_id: uuid.UUID, limit: int = 20) -> list[Deal]:
        result = await self.session.execute(
            select(Deal)
            .where(Deal.contact_id == contact_id)
            .options(joinedload(Deal.stage))
            .order_by(Deal.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def add(self, deal: Deal) -> Deal:
        self.session.add(deal)
        await self.session.flush()
        return deal

    async def delete(self, deal: Deal) -> None:
        await self.session.delete(deal)
        await self.session.flush()


def _filtered(filters: DealFilters) -> Select[Deal]:
    query = select(Deal)
    if filters.search:
        query = query.where(Deal.title.ilike(like_pattern(filters.search)))
    if filters.stage_id:
        query = query.where(Deal.stage_id == filters.stage_id)
    if filters.contact_id:
        query = query.where(Deal.contact_id == filters.contact_id)
    if filters.company_id:
        query = query.where(Deal.company_id == filters.company_id)
    if filters.owner_id:
        query = query.where(Deal.owner_id == filters.owner_id)
    return query


def _sorted(query: Select[Deal], filters: DealFilters) -> Select[Deal]:
    if filters.sort is None:
        return query.order_by(Deal.created_at.desc())
    if filters.sort == "stage":
        query = query.join(PipelineStage, Deal.stage_id == PipelineStage.id)
    return query.order_by(sort_by(_SORT_COLUMNS[filters.sort], filters.order), Deal.id)
