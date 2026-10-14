from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.modules.webhooks.service import WebhookService


def get_webhook_service(session: SessionDep) -> WebhookService:
    return WebhookService(session)


WebhookServiceDep = Annotated[WebhookService, Depends(get_webhook_service)]
