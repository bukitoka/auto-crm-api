import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.core.exceptions import NotFoundError
from app.core.security import generate_secret
from app.modules.webhooks.models import WebhookSubscription
from app.modules.webhooks.repository import WebhookRepository
from app.modules.webhooks.schemas import WebhookCreate, WebhookRead, WebhookUpdate
from app.shared.pagination import Page, PageParams


class WebhookService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WebhookRepository(session)

    @staticmethod
    def list_events() -> list[str]:
        return [event.value for event in Event]

    async def get(self, webhook_id: uuid.UUID) -> WebhookSubscription:
        webhook = await self.repo.get(webhook_id)
        if webhook is None:
            raise NotFoundError("Webhook subscription not found")
        return webhook

    async def list_page(self, params: PageParams) -> Page[WebhookRead]:
        items, total = await self.repo.list_page(offset=params.offset, limit=params.size)
        return Page[WebhookRead].from_items(items, total, params)

    async def create(self, data: WebhookCreate) -> WebhookSubscription:
        webhook = WebhookSubscription(
            event=data.event,
            target_url=str(data.target_url),
            is_active=data.is_active,
            secret=generate_secret(),
        )
        await self.repo.add(webhook)
        await self.session.commit()
        await self.session.refresh(webhook)
        return webhook

    async def update(self, webhook_id: uuid.UUID, data: WebhookUpdate) -> WebhookSubscription:
        webhook = await self.get(webhook_id)
        changes = data.model_dump(exclude_unset=True)
        if "target_url" in changes:
            changes["target_url"] = str(changes["target_url"])
        for field, value in changes.items():
            setattr(webhook, field, value)
        await self.session.commit()
        await self.session.refresh(webhook)
        return webhook

    async def delete(self, webhook_id: uuid.UUID) -> None:
        webhook = await self.get(webhook_id)
        await self.repo.delete(webhook)
        await self.session.commit()
