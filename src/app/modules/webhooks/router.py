import uuid
from datetime import datetime

from fastapi import APIRouter, status
from sqlalchemy import select

from app.core.database import SessionDep
from app.modules.auth.dependencies import CurrentUser, SuperAdminUser
from app.modules.webhooks.delivery import retry_delivery
from app.modules.webhooks.dependencies import WebhookServiceDep
from app.modules.webhooks.models import WebhookDelivery
from app.modules.webhooks.schemas import WebhookCreate, WebhookRead, WebhookUpdate
from app.modules.webhooks.service import WebhookService
from app.shared.pagination import Page, PageParamsDep
from app.shared.schemas import ORMModel

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/events", response_model=list[str])
async def list_events(_: CurrentUser):
    return WebhookService.list_events()


@router.get("", response_model=Page[WebhookRead])
async def list_webhooks(_: SuperAdminUser, service: WebhookServiceDep, params: PageParamsDep):
    return await service.list_page(params)


@router.post("", response_model=WebhookRead, status_code=status.HTTP_201_CREATED)
async def create_webhook(_: SuperAdminUser, data: WebhookCreate, service: WebhookServiceDep):
    return await service.create(data)


@router.patch("/{webhook_id}", response_model=WebhookRead)
async def update_webhook(
    _: SuperAdminUser, webhook_id: uuid.UUID, data: WebhookUpdate, service: WebhookServiceDep
):
    return await service.update(webhook_id, data)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(_: SuperAdminUser, webhook_id: uuid.UUID, service: WebhookServiceDep):
    await service.delete(webhook_id)


class DeliveryRead(ORMModel):
    id: uuid.UUID
    subscription_id: uuid.UUID | None
    event: str
    attempts: int
    delivered: bool
    status_code: int | None
    error: str | None
    created_at: datetime
    updated_at: datetime


@router.get("/deliveries", response_model=list[DeliveryRead])
async def delivery_history(_: SuperAdminUser, session: SessionDep):
    return (
        await session.scalars(
            select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(100)
        )
    ).all()


@router.post("/deliveries/{delivery_id}/retry", response_model=DeliveryRead)
async def retry_webhook_delivery(_: SuperAdminUser, delivery_id: uuid.UUID, session: SessionDep):
    return await retry_delivery(session, delivery_id)
