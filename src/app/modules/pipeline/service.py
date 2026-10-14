from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pipeline.models import PipelineStage
from app.modules.pipeline.repository import PipelineRepository


class PipelineService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = PipelineRepository(session)

    async def list_stages(self) -> list[PipelineStage]:
        return await self.repo.list_stages()
