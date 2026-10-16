import hashlib
import hmac
import json
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from pydantic import AnyHttpUrl

from app.core.events import Event
from app.core.exceptions import NotFoundError
from app.modules.webhooks import delivery
from app.modules.webhooks.schemas import WebhookCreate, WebhookUpdate
from app.modules.webhooks.service import WebhookService
from app.shared.pagination import PageParams
from tests.unit.conftest import make_webhook, mock_repos


@pytest.fixture
def service(session: AsyncMock) -> WebhookService:
    service = WebhookService(session)
    mock_repos(service, "repo")
    return service


def test_list_events_returns_every_event_name() -> None:
    assert WebhookService.list_events() == [event.value for event in Event]
    assert "deal.stage_changed" in WebhookService.list_events()


async def test_create_generates_a_secret_and_stores_url_as_text(service: WebhookService) -> None:
    data = WebhookCreate(event=Event.DEAL_WON, target_url=AnyHttpUrl("http://n8n.local/won"))

    webhook = await service.create(data)

    assert webhook.target_url == "http://n8n.local/won"
    assert len(webhook.secret) >= 32
    assert webhook.is_active is True
    service.session.commit.assert_awaited_once()


async def test_update_changes_only_sent_fields(service: WebhookService) -> None:
    webhook = make_webhook(is_active=True, secret="keep-me")
    service.repo.get.return_value = webhook

    await service.update(
        webhook.id, WebhookUpdate(is_active=False, target_url=AnyHttpUrl("https://new.io/x"))
    )

    assert webhook.is_active is False
    assert webhook.target_url == "https://new.io/x"
    assert webhook.secret == "keep-me"


async def test_unknown_webhook_is_not_found(service: WebhookService) -> None:
    service.repo.get.return_value = None

    with pytest.raises(NotFoundError, match="Webhook subscription not found"):
        await service.delete(make_webhook().id)


async def test_delete_removes_the_webhook(service: WebhookService) -> None:
    webhook = make_webhook()
    service.repo.get.return_value = webhook

    await service.delete(webhook.id)

    service.repo.delete.assert_awaited_once_with(webhook)


async def test_list_page(service: WebhookService) -> None:
    service.repo.list_page.return_value = ([make_webhook()], 1)

    page = await service.list_page(PageParams())

    assert page.items[0].event == Event.DEAL_WON


def test_sign_payload_is_hex_hmac_sha256_of_the_body() -> None:
    body = b'{"event":"deal.won"}'
    expected = hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    assert delivery.sign_payload("secret", body) == f"sha256={expected}"


@pytest.fixture
def subscriptions(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """The active subscriptions `deliver_event` will find (no database involved)."""
    found: list[Any] = []
    repository = MagicMock()
    repository.return_value.list_active_for_event = AsyncMock(return_value=found)
    monkeypatch.setattr(delivery, "WebhookRepository", repository)
    monkeypatch.setattr(delivery, "SessionFactory", MagicMock())  # async context manager
    return found


@pytest.fixture
def sent_requests(monkeypatch: pytest.MonkeyPatch) -> Callable[[int], list[httpx.Request]]:
    """Route webhook HTTP calls to an in-memory transport answering with `status_code`."""

    def install(status_code: int = 200) -> list[httpx.Request]:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(status_code)

        real_client = httpx.AsyncClient

        def client_with_mock_transport(**kwargs: Any) -> httpx.AsyncClient:
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(delivery.httpx, "AsyncClient", client_with_mock_transport)
        return requests

    return install


async def test_deliver_event_posts_a_signed_payload_to_each_subscription(
    subscriptions: list[Any], sent_requests: Callable[[int], list[httpx.Request]]
) -> None:
    subscriptions.extend(
        [
            make_webhook(target_url="http://n8n.local/a", secret="secret-a"),
            make_webhook(target_url="http://n8n.local/b", secret="secret-b"),
        ]
    )
    requests = sent_requests(200)

    await delivery.deliver_event(Event.DEAL_WON, {"id": "123"})

    assert sorted(str(r.url) for r in requests) == ["http://n8n.local/a", "http://n8n.local/b"]
    for request, secret in zip(
        sorted(requests, key=lambda r: str(r.url)), ["secret-a", "secret-b"], strict=True
    ):
        assert request.headers["X-AutoCRM-Event"] == "deal.won"
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["X-AutoCRM-Signature"] == delivery.sign_payload(
            secret, request.content
        )
        body = json.loads(request.content)
        assert body["event"] == "deal.won"
        assert body["data"] == {"id": "123"}
        assert body["occurred_at"]


async def test_deliver_event_without_subscriptions_sends_nothing(
    subscriptions: list[Any], sent_requests: Callable[[int], list[httpx.Request]]
) -> None:
    requests = sent_requests(200)

    await delivery.deliver_event(Event.TASK_CREATED, {})

    assert requests == []


async def test_failed_delivery_is_logged_not_raised(
    subscriptions: list[Any],
    sent_requests: Callable[[int], list[httpx.Request]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    subscriptions.append(make_webhook(target_url="http://n8n.local/down"))
    requests = sent_requests(500)

    await delivery.deliver_event(Event.DEAL_WON, {})

    assert len(requests) == 1
    assert "failed" in caplog.text
