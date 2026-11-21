"""Delivers domain events to webhook subscriptions (e.g. n8n).

Request body: {"event": "...", "occurred_at": "...", "data": {...}}
Headers:
  X-AutoCRM-Event: <event name>
  X-AutoCRM-Signature: sha256=<hex HMAC-SHA256 of the raw body, keyed by the subscription secret>
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionFactory
from app.core.events import Event
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.webhooks.models import WebhookDelivery, WebhookSubscription
from app.modules.webhooks.repository import WebhookRepository
from app.shared.utils import utc_now

logger = logging.getLogger(__name__)


def sign_payload(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def deliver_event(event: Event, data: dict[str, Any]) -> None:
    """Event handler: POST the event to every active subscription for it."""
    async with SessionFactory() as session:
        subscriptions = await WebhookRepository(session).list_active_for_event(event)
    if not subscriptions:
        return

    payload = {"event": event.value, "occurred_at": utc_now().isoformat(), "data": data}
    async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
        await asyncio.gather(
            *(_record_delivery(client, sub, event, payload) for sub in subscriptions)
        )


async def _record_delivery(
    client: httpx.AsyncClient,
    subscription: WebhookSubscription,
    event: Event,
    payload: dict[str, Any],
) -> None:
    async with SessionFactory() as session:
        item = WebhookDelivery(
            id=uuid.uuid7(), subscription_id=subscription.id, event=event, payload=payload
        )
        session.add(item)
        await session.commit()
        await _attempt(client, subscription, item)
        await session.commit()


async def retry_delivery(session: AsyncSession, delivery_id: uuid.UUID) -> WebhookDelivery:
    item = await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.id == delivery_id).with_for_update()
    )
    if item is None:
        raise NotFoundError("Delivery not found")
    if item.delivered:
        raise ConflictError("This delivery already succeeded")
    if item.attempts == 0 and (utc_now() - item.created_at).total_seconds() < (
        settings.webhook_timeout_seconds + 10
    ):
        raise ConflictError("This delivery is still in progress")
    subscription = (
        await session.get(WebhookSubscription, item.subscription_id)
        if item.subscription_id
        else None
    )
    if subscription is None or not subscription.is_active or subscription.event != item.event:
        raise ConflictError("This event no longer has an active matching subscription")
    async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
        await _attempt(client, subscription, item)
    await session.commit()
    await session.refresh(item)
    return item


async def _attempt(
    client: httpx.AsyncClient, subscription: WebhookSubscription, item: WebhookDelivery
) -> None:
    body = json.dumps(item.payload, sort_keys=True).encode()
    headers = {
        "Content-Type": "application/json",
        "X-AutoCRM-Event": str(item.event),
        "X-AutoCRM-Delivery": str(item.id),
        "X-AutoCRM-Signature": sign_payload(subscription.secret, body),
    }
    item.attempts = (item.attempts or 0) + 1
    item.status_code = None
    item.error = None
    try:
        response = await client.post(subscription.target_url, content=body, headers=headers)
        item.status_code = response.status_code
        response.raise_for_status()
        item.delivered = True
    except httpx.HTTPError as exc:
        item.delivered = False
        item.error = (
            f"HTTP {item.status_code}" if item.status_code is not None else type(exc).__name__
        )
        logger.warning("Webhook delivery of %s failed: %s", item.event, item.error)
