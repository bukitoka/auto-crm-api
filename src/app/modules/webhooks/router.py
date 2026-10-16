import uuid

from fastapi import APIRouter, status

from app.modules.auth.dependencies import CurrentUser, SuperAdminUser
from app.modules.webhooks.dependencies import WebhookServiceDep
from app.modules.webhooks.schemas import WebhookCreate, WebhookRead, WebhookUpdate
from app.modules.webhooks.service import WebhookService
from app.shared.pagination import Page, PageParamsDep

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
