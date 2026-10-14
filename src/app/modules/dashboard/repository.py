from datetime import datetime
from decimal import Decimal

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact
from app.modules.deals.models import Deal
from app.modules.pipeline.models import PipelineStage


class DashboardRepository:
    """Aggregate queries for the dashboard."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def open_pipeline_value(self) -> Decimal:
        result = await self.session.scalar(
            select(func.coalesce(func.sum(Deal.value), 0))
            .join(Deal.stage)
            .where(PipelineStage.is_won.is_(False), PipelineStage.is_lost.is_(False))
        )
        return Decimal(result or 0)

    async def won_value_since(self, since: datetime) -> Decimal:
        result = await self.session.scalar(
            select(func.coalesce(func.sum(Deal.value), 0))
            .join(Deal.stage)
            .where(PipelineStage.is_won.is_(True), Deal.closed_at >= since)
        )
        return Decimal(result or 0)

    async def contacts_created_since(self, since: datetime) -> int:
        result = await self.session.scalar(
            select(func.count()).select_from(Contact).where(Contact.created_at >= since)
        )
        return result or 0

    async def pipeline_by_stage(self) -> list[Row]:
        """One row per stage: (stage_id, stage_name, deal_count, total_value)."""
        query = (
            select(
                PipelineStage.id.label("stage_id"),
                PipelineStage.name.label("stage_name"),
                func.count(Deal.id).label("deal_count"),
                func.coalesce(func.sum(Deal.value), 0).label("total_value"),
            )
            .outerjoin(Deal, Deal.stage_id == PipelineStage.id)
            .group_by(PipelineStage.id)
            .order_by(PipelineStage.position)
        )
        result = await self.session.execute(query)
        return list(result.all())
