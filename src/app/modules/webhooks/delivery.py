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
from typing import Any

import httpx

from app.core.config import settings
from app.core.database import SessionFactory
from app.core.events import Event
from app.modules.webhooks.models import WebhookSubscription
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

    body = json.dumps(
        {"event": event.value, "occurred_at": utc_now().isoformat(), "data": data}
    ).encode()
    async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds) as client:
        await asyncio.gather(*(_send(client, sub, event, body) for sub in subscriptions))


async def _send(
    client: httpx.AsyncClient, subscription: WebhookSubscription, event: Event, body: bytes
) -> None:
    headers = {
        "Content-Type": "application/json",
        "X-AutoCRM-Event": event.value,
        "X-AutoCRM-Signature": sign_payload(subscription.secret, body),
    }
    try:
        response = await client.post(subscription.target_url, content=body, headers=headers)
        response.raise_for_status()
        logger.info("Delivered %s to %s", event, subscription.target_url)
    except httpx.HTTPError as exc:
        # Failures are logged only; they never affect the API request.
        logger.warning(
            "Webhook delivery of %s to %s failed: %s", event, subscription.target_url, exc
        )
