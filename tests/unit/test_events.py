from collections.abc import Iterator
from typing import Any

import pytest

from app.core import events
from app.core.events import Event


@pytest.fixture(autouse=True)
def no_handlers(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts with an empty handler list (the app may have subscribed one)."""
    monkeypatch.setattr(events, "_handlers", [])
    yield


async def test_publish_runs_every_subscribed_handler() -> None:
    received: list[tuple[str, Event, dict[str, Any]]] = []

    async def first(event: Event, data: dict[str, Any]) -> None:
        received.append(("first", event, data))

    async def second(event: Event, data: dict[str, Any]) -> None:
        received.append(("second", event, data))

    events.subscribe(first)
    events.subscribe(second)

    events.publish(Event.DEAL_WON, {"id": "1"})
    await events.drain()

    assert received == [
        ("first", Event.DEAL_WON, {"id": "1"}),
        ("second", Event.DEAL_WON, {"id": "1"}),
    ]


async def test_subscribing_twice_registers_the_handler_once() -> None:
    calls: list[Event] = []

    async def handler(event: Event, data: dict[str, Any]) -> None:
        calls.append(event)

    events.subscribe(handler)
    events.subscribe(handler)

    events.publish(Event.TASK_CREATED, {})
    await events.drain()

    assert calls == [Event.TASK_CREATED]


async def test_unsubscribed_handler_is_not_called() -> None:
    calls: list[Event] = []

    async def handler(event: Event, data: dict[str, Any]) -> None:
        calls.append(event)

    events.subscribe(handler)
    events.unsubscribe(handler)
    events.unsubscribe(handler)  # unsubscribing again is harmless

    events.publish(Event.TASK_CREATED, {})
    await events.drain()

    assert calls == []


async def test_failing_handler_is_logged_and_does_not_stop_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[Event] = []

    async def broken(event: Event, data: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    async def working(event: Event, data: dict[str, Any]) -> None:
        calls.append(event)

    events.subscribe(broken)
    events.subscribe(working)

    events.publish(Event.CONTACT_CREATED, {})
    await events.drain()

    assert calls == [Event.CONTACT_CREATED]
    assert "failed for contact.created" in caplog.text


async def test_drain_without_pending_handlers_returns_immediately() -> None:
    await events.drain()
