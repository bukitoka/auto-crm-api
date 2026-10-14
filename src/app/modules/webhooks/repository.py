import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.webhooks.models import WebhookSubscription


class WebhookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, webhook_id: uuid.UUID) -> WebhookSubscription | None:
        return await self.session.get(WebhookSubscription, webhook_id)

    async def list_page(self, *, offset: int, limit: int) -> tuple[list[WebhookSubscription], int]:
        total = await self.session.scalar(select(func.count()).select_from(WebhookSubscription))
        result = await self.session.execute(
            select(WebhookSubscription)
            .order_by(WebhookSubscription.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars()), total or 0

    async def list_active_for_event(self, event: Event) -> list[WebhookSubscription]:
        result = await self.session.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.event == event, WebhookSubscription.is_active.is_(True)
            )
        )
        return list(result.scalars())

    async def add(self, webhook: WebhookSubscription) -> WebhookSubscription:
        self.session.add(webhook)
        await self.session.flush()
        return webhook

    async def delete(self, webhook: WebhookSubscription) -> None:
        await self.session.delete(webhook)
        await self.session.flush()
