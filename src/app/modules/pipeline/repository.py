import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.deals.models import Deal
from app.modules.pipeline.models import PipelineStage
from app.shared.utils import utc_now


class PipelineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_stages(self) -> list[PipelineStage]:
        result = await self.session.execute(select(PipelineStage).order_by(PipelineStage.position))
        return list(result.scalars())

    async def get_stage(self, stage_id: uuid.UUID) -> PipelineStage | None:
        return await self.session.get(PipelineStage, stage_id)

    async def get_default_stage(self) -> PipelineStage | None:
        """The first open stage (lowest position that is neither won nor lost)."""
        result = await self.session.execute(
            select(PipelineStage)
            .where(PipelineStage.is_won.is_(False), PipelineStage.is_lost.is_(False))
            .order_by(PipelineStage.position)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def deal_counts(self) -> dict[uuid.UUID, int]:
        result = await self.session.execute(
            select(Deal.stage_id, func.count()).group_by(Deal.stage_id)
        )
        return {stage_id: count for stage_id, count in result.all()}

    async def deal_ids_in_stage(self, stage_id: uuid.UUID) -> list[uuid.UUID]:
        result = await self.session.execute(select(Deal.id).where(Deal.stage_id == stage_id))
        return list(result.scalars())

    async def set_deals_closed(self, stage_id: uuid.UUID, *, closed: bool) -> None:
        """Set (or clear) `closed_at` on every deal in a stage that became won/lost (or open)."""
        closed_at = func.coalesce(Deal.closed_at, utc_now()) if closed else None
        await self.session.execute(
            update(Deal).where(Deal.stage_id == stage_id).values(closed_at=closed_at)
        )

    async def add(self, stage: PipelineStage) -> PipelineStage:
        self.session.add(stage)
        await self.session.flush()
        return stage

    async def delete(self, stage: PipelineStage) -> None:
        await self.session.delete(stage)
        await self.session.flush()
