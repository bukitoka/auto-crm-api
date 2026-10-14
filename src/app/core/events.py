"""Tiny in-process event bus for domain events.

Services call `publish(...)` after a successful commit. Every subscribed handler
runs in its own background asyncio task, so a slow or failing handler never
breaks the HTTP request. The webhooks module subscribes a handler at startup.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class Event(StrEnum):
    CONTACT_CREATED = "contact.created"
    CONTACT_UPDATED = "contact.updated"
    DEAL_CREATED = "deal.created"
    DEAL_STAGE_CHANGED = "deal.stage_changed"
    DEAL_WON = "deal.won"
    DEAL_LOST = "deal.lost"
    TASK_CREATED = "task.created"
    TASK_COMPLETED = "task.completed"


EventHandler = Callable[[Event, dict[str, Any]], Awaitable[None]]

_handlers: list[EventHandler] = []
_pending: set[asyncio.Task[None]] = set()


def subscribe(handler: EventHandler) -> None:
    if handler not in _handlers:
        _handlers.append(handler)


def unsubscribe(handler: EventHandler) -> None:
    if handler in _handlers:
        _handlers.remove(handler)


def publish(event: Event, data: dict[str, Any]) -> None:
    """Schedule all handlers for `event`. `data` must be JSON-serializable."""
    for handler in _handlers:
        task = asyncio.create_task(_run_handler(handler, event, data))
        _pending.add(task)  # keep a reference so the task is not garbage collected
        task.add_done_callback(_pending.discard)


async def drain() -> None:
    """Wait for in-flight handlers (used on shutdown and in tests)."""
    if _pending:
        await asyncio.gather(*_pending, return_exceptions=True)


async def _run_handler(handler: EventHandler, event: Event, data: dict[str, Any]) -> None:
    try:
        await handler(event, data)
    except Exception:
        logger.exception("Event handler %r failed for %s", handler, event)
