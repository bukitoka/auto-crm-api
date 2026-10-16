import hashlib
import hmac
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from app.core.events import Event
from app.modules.webhooks import delivery


def test_sign_payload_matches_hmac_sha256() -> None:
    body = b'{"event":"deal.won"}'
    expected = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert delivery.sign_payload("secret", body) == f"sha256={expected}"


async def test_webhook_management_is_super_admin_only(
    client: AsyncClient, super_admin_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    payload = {"event": "deal.won", "target_url": "http://n8n.local/webhook/won"}

    forbidden = await client.post("/api/v1/webhooks", json=payload, headers=admin_headers)
    assert forbidden.status_code == 403

    created = await client.post("/api/v1/webhooks", json=payload, headers=super_admin_headers)
    assert created.status_code == 201
    assert len(created.json()["secret"]) > 20

    events = await client.get("/api/v1/webhooks/events", headers=admin_headers)
    assert "deal.stage_changed" in events.json()


async def test_deliver_event_posts_signed_payload(
    client: AsyncClient, super_admin_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    webhook = (
        await client.post(
            "/api/v1/webhooks",
            json={"event": "contact.created", "target_url": "http://n8n.local/hook"},
            headers=super_admin_headers,
        )
    ).json()

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    real_client = httpx.AsyncClient

    def client_with_mock_transport(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(delivery.httpx, "AsyncClient", client_with_mock_transport)

    await delivery.deliver_event(Event.CONTACT_CREATED, {"id": "123"})

    assert len(requests) == 1
    request = requests[0]
    assert request.headers["X-AutoCRM-Event"] == "contact.created"
    assert request.headers["X-AutoCRM-Signature"] == delivery.sign_payload(
        webhook["secret"], request.content
    )


async def test_super_admin_can_list_update_and_delete_webhooks(
    client: AsyncClient, super_admin_headers: dict[str, str]
) -> None:
    webhook = (
        await client.post(
            "/api/v1/webhooks",
            json={"event": "deal.won", "target_url": "http://n8n.local/won"},
            headers=super_admin_headers,
        )
    ).json()

    listed = await client.get("/api/v1/webhooks", headers=super_admin_headers)
    assert [w["id"] for w in listed.json()["items"]] == [webhook["id"]]

    updated = await client.patch(
        f"/api/v1/webhooks/{webhook['id']}", json={"is_active": False}, headers=super_admin_headers
    )
    assert updated.json()["is_active"] is False
    assert updated.json()["secret"] == webhook["secret"]

    deleted = await client.delete(f"/api/v1/webhooks/{webhook['id']}", headers=super_admin_headers)
    assert deleted.status_code == 204
    again = await client.delete(f"/api/v1/webhooks/{webhook['id']}", headers=super_admin_headers)
    assert again.status_code == 404


async def test_inactive_webhooks_are_not_called(
    client: AsyncClient, super_admin_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.post(
        "/api/v1/webhooks",
        json={"event": "contact.created", "target_url": "http://n8n.local/x", "is_active": False},
        headers=super_admin_headers,
    )

    def fail_if_called(**kwargs: Any) -> httpx.AsyncClient:
        raise AssertionError("no HTTP call expected")

    monkeypatch.setattr(delivery.httpx, "AsyncClient", fail_if_called)

    await delivery.deliver_event(Event.CONTACT_CREATED, {"id": "1"})
