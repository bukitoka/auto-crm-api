import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pipeline.models import PipelineStage


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
