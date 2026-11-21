from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient

from app.core.events import Event
from app.modules.webhooks import delivery
from app.modules.workspace_sync import router as sync
from app.modules.workspace_sync.providers import ExternalEvent, ExternalMail
from app.shared.utils import today_utc, utc_now
from tests.fakes import FakeStorage

API = "/api/v1"


async def test_private_document_and_contact_merge(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    storage: FakeStorage,
) -> None:
    async def contact(data: dict, headers: dict[str, str]) -> str:
        response = await client.post(f"{API}/contacts", json=data, headers=headers)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    keep = await contact({"first_name": "Jane", "last_name": "Lee"}, admin_headers)
    source = await contact(
        {"first_name": "jane", "last_name": "Lee", "email": "jane@example.com"}, admin_headers
    )
    other = await contact({"first_name": "Jane", "last_name": "Lee"}, member_headers)
    matches = await client.get(f"{API}/duplicates/contact/{keep}", headers=admin_headers)
    assert [row["id"] for row in matches.json()["candidates"]] == [source]

    files = {"file": ("contract.txt", b"Renewal terms", "text/plain")}
    denied = await client.post(
        f"{API}/documents", files=files, data={"contact_id": other}, headers=admin_headers
    )
    assert denied.status_code == 404
    uploaded = await client.post(
        f"{API}/documents",
        files=files,
        data={"contact_id": source, "notes": "Annual renewal"},
        headers=admin_headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()
    assert document["contact_id"] == source
    assert "object_key" not in document
    path = f"{API}/documents/{document['id']}"
    assert (await client.get(f"{path}/download", headers=member_headers)).status_code == 404
    assert (await client.get(f"{path}/download", headers=admin_headers)).status_code == 200
    assert (await client.get(f"{API}/documents", headers=member_headers)).json() == []
    assert (
        await client.get(f"{API}/documents", params={"search": "annual"}, headers=admin_headers)
    ).json() == [document]
    assert (
        await client.get(f"{API}/documents", params={"contact_id": keep}, headers=admin_headers)
    ).json() == []

    task = await client.post(
        f"{API}/tasks", json={"title": "Read contract", "contact_id": source}, headers=admin_headers
    )
    assert task.status_code == 201, task.text
    begins = utc_now() + timedelta(days=1)
    event = await client.post(
        f"{API}/calendar/events",
        json={
            "title": "Contract review",
            "contact_id": source,
            "starts_at": begins.isoformat(),
            "ends_at": (begins + timedelta(hours=1)).isoformat(),
        },
        headers=admin_headers,
    )
    assert event.status_code == 201, event.text
    activity = await client.post(
        f"{API}/activities",
        json={"type": "call", "subject": "Contract call", "contact_id": source},
        headers=admin_headers,
    )
    assert activity.status_code == 201, activity.text
    merge = await client.post(
        f"{API}/duplicates/contact/merge",
        json={"keep_id": keep, "duplicate_id": source},
        headers=admin_headers,
    )
    assert merge.status_code == 200, merge.text
    assert (await client.get(f"{API}/contacts/{source}", headers=admin_headers)).status_code == 404
    kept = (await client.get(f"{API}/contacts/{keep}", headers=admin_headers)).json()
    assert kept["email"] == "jane@example.com"
    assert (await client.get(f"{API}/tasks/{task.json()['id']}", headers=admin_headers)).json()[
        "contact_id"
    ] == keep
    preserved_event = await client.get(
        f"{API}/calendar/events/{event.json()['id']}", headers=admin_headers
    )
    assert preserved_event.json()["contact_id"] == keep
    preserved_activities = await client.get(
        f"{API}/activities", params={"contact_id": keep}, headers=admin_headers
    )
    assert [row["id"] for row in preserved_activities.json()["items"]] == [activity.json()["id"]]
    linked = (
        await client.get(f"{API}/documents", params={"contact_id": keep}, headers=admin_headers)
    ).json()
    assert linked[0]["id"] == document["id"]
    updated = await client.put(
        path, json={"notes": "Updated", "contact_id": keep}, headers=admin_headers
    )
    assert updated.json()["notes"] == "Updated"
    assert (await client.delete(path, headers=admin_headers)).status_code == 204
    assert not storage.files


async def test_automation_lead_routing_and_deadlines(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    super_admin_headers: dict[str, str],
    api_key_headers: dict[str, str],
) -> None:
    path = f"{API}/integrations/lead-routing"
    assert (await client.get(path, headers=admin_headers)).status_code == 403
    assert (await client.get(path, headers=super_admin_headers)).json()["enabled"] is False
    config = {"enabled": True, "response_hours": 4}
    assert (await client.put(path, json=config, headers=super_admin_headers)).json() == config

    owners = set()
    for index in range(2):
        response = await client.post(
            f"{API}/integrations/leads",
            json={
                "first_name": "Lead",
                "email": f"lead{index}@example.com",
                "company_name": "Example",
            },
            headers=api_key_headers,
        )
        assert response.status_code == 201, response.text
        owners.add(response.json()["owner_id"])
    assert len(owners) == 2

    incoming = (await client.get(f"{API}/dashboard/follow-ups", headers=admin_headers)).json()
    assert len(incoming) == 1
    assert incoming[0]["response_due_at"]
    assert incoming[0]["response_overdue"] is False
    tomorrow = today_utc() + timedelta(days=1)
    task = await client.post(
        f"{API}/tasks",
        json={"title": "Lead check", "due_date": tomorrow.isoformat()},
        headers=admin_headers,
    )
    assert task.status_code == 201
    window = {"start": today_utc().isoformat(), "end": (tomorrow + timedelta(days=1)).isoformat()}
    own = await client.get(f"{API}/calendar/deadlines", params=window, headers=admin_headers)
    assert own.json() == [
        {
            "id": task.json()["id"],
            "title": "Lead check",
            "day": tomorrow.isoformat(),
            "kind": "task",
        }
    ]
    assert (
        await client.get(f"{API}/calendar/deadlines", params=window, headers=member_headers)
    ).json() == []


async def test_webhook_history_and_retry(
    client: AsyncClient,
    admin_headers: dict[str, str],
    super_admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await client.post(
        f"{API}/webhooks",
        json={"event": "deal.won", "target_url": "https://n8n.example.com/sales"},
        headers=super_admin_headers,
    )
    assert created.status_code == 201
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(502 if len(requests) == 1 else 200)

    real_client = httpx.AsyncClient

    def transport(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(delivery.httpx, "AsyncClient", transport)
    await delivery.deliver_event(Event.DEAL_WON, {"id": "deal-1"})
    path = f"{API}/webhooks/deliveries"
    assert (await client.get(path, headers=admin_headers)).status_code == 403
    row = (await client.get(path, headers=super_admin_headers)).json()[0]
    assert row["attempts"] == 1 and row["error"] == "HTTP 502"
    assert "payload" not in row
    retry = f"{path}/{row['id']}/retry"
    result = (await client.post(retry, headers=super_admin_headers)).json()
    assert result["attempts"] == 2 and result["delivered"]
    assert requests[0].content == requests[1].content
    assert requests[0].headers["X-AutoCRM-Delivery"] == requests[1].headers["X-AutoCRM-Delivery"]
    assert (await client.post(retry, headers=super_admin_headers)).status_code == 409


async def test_provider_import_dedupes_and_links_to_owned_contacts(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync.settings, "google_sync_client_id", "test-client")
    monkeypatch.setattr(sync.settings, "google_sync_client_secret", "test-secret")
    result = await client.post(
        f"{API}/contacts",
        json={"first_name": "Jane", "email": "jane@example.com"},
        headers=admin_headers,
    )
    contact = result.json()["id"]
    start = utc_now() + timedelta(days=1)
    meeting = ExternalEvent(
        "meeting", "Renewal", start, start + timedelta(hours=1), ("jane@example.com",)
    )
    mail = ExternalMail("reply", "jane@example.com", "Re: Renewal", utc_now())

    async def exchange(*_: object) -> str:
        return "temporary-provider-token"

    async def account(*_: object):
        return "acct", [meeting], [mail]

    from app.modules.workspace_sync.providers import Provider

    monkeypatch.setattr(Provider, "exchange", exchange)
    monkeypatch.setattr(sync, "fetch_account", account)
    base = f"{API}/workspace-sync/google"
    options = (await client.post(f"{base}/start", headers=admin_headers)).json()
    query = parse_qs(urlparse(options["url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    payload = {"state": query["state"][0], "code": "temporary-code"}
    assert (
        await client.post(f"{base}/complete", json=payload, headers=member_headers)
    ).status_code == 400
    first = await client.post(f"{base}/complete", json=payload, headers=admin_headers)
    assert first.json() == {"events_added": 1, "events_updated": 0, "emails_logged": 1}
    second = await client.post(f"{base}/complete", json=payload, headers=admin_headers)
    assert second.json() == {"events_added": 0, "events_updated": 0, "emails_logged": 0}
    events = (
        await client.get(
            f"{API}/calendar/events",
            params={"start": utc_now().isoformat(), "end": (start + timedelta(days=1)).isoformat()},
            headers=admin_headers,
        )
    ).json()
    assert events[0]["contact_id"] == contact
    activity = (
        await client.get(f"{API}/activities", params={"contact_id": contact}, headers=admin_headers)
    ).json()
    assert activity["items"][0]["subject"] == "Re: Renewal"
