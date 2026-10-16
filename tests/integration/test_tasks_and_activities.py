from datetime import timedelta
from typing import Any

from httpx import AsyncClient

from app.core.events import Event
from app.shared.utils import today_utc


async def _contact(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.post("/api/v1/contacts", json={"first_name": "Jane"}, headers=headers)
    return response.json()


async def test_task_lifecycle(
    client: AsyncClient,
    admin_headers: dict[str, str],
    published_events: list[tuple[Event, dict[str, Any]]],
) -> None:
    contact = await _contact(client, admin_headers)
    created = await client.post(
        "/api/v1/tasks",
        json={"title": "Call Jane", "contact_id": contact["id"], "priority": "high"},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["assignee"]["full_name"] == "Ada Admin"
    assert task["created_by"]["full_name"] == "Ada Admin"
    assert task["contact"]["first_name"] == "Jane"
    assert task["status"] == "todo"

    done = await client.patch(
        f"/api/v1/tasks/{task['id']}", json={"status": "done"}, headers=admin_headers
    )
    assert done.json()["completed_at"] is not None

    reopened = await client.patch(
        f"/api/v1/tasks/{task['id']}", json={"status": "todo"}, headers=admin_headers
    )
    assert reopened.json()["completed_at"] is None
    task_events = [event for event, _ in published_events if event.startswith("task.")]
    assert task_events == [Event.TASK_CREATED, Event.TASK_COMPLETED]

    fetched = await client.get(f"/api/v1/tasks/{task['id']}", headers=admin_headers)
    assert fetched.json()["title"] == "Call Jane"

    deleted = await client.delete(f"/api/v1/tasks/{task['id']}", headers=admin_headers)
    assert deleted.status_code == 204
    assert (
        await client.get(f"/api/v1/tasks/{task['id']}", headers=admin_headers)
    ).status_code == 404


async def test_task_filters(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    yesterday = (today_utc() - timedelta(days=1)).isoformat()
    tomorrow = (today_utc() + timedelta(days=1)).isoformat()
    contact = await _contact(client, admin_headers)
    deal = (await client.post("/api/v1/deals", json={"title": "D"}, headers=admin_headers)).json()
    for title, due_date, status in [
        ("Late", yesterday, "todo"),
        ("Late but done", yesterday, "done"),
        ("Soon", tomorrow, "in_progress"),
    ]:
        await client.post(
            "/api/v1/tasks",
            json={
                "title": title,
                "due_date": due_date,
                "status": status,
                "contact_id": contact["id"],
                "deal_id": deal["id"],
            },
            headers=admin_headers,
        )
    await client.post("/api/v1/tasks", json={"title": "No date"}, headers=admin_headers)
    me = (await client.get("/api/v1/auth/me", headers=admin_headers)).json()

    async def titles(query: str) -> list[str]:
        response = await client.get(f"/api/v1/tasks?{query}", headers=admin_headers)
        assert response.status_code == 200, response.text
        return [task["title"] for task in response.json()["items"]]

    assert await titles("overdue=true") == ["Late"]
    # A task without a due date is never overdue.
    assert sorted(await titles("overdue=false")) == ["Late but done", "No date", "Soon"]
    assert await titles("status=in_progress") == ["Soon"]
    assert len(await titles(f"assignee_id={me['id']}")) == 4
    assert len(await titles(f"contact_id={contact['id']}&deal_id={deal['id']}")) == 3
    assert await titles("search=soon") == ["Soon"]


async def test_task_with_unknown_assignee_is_404(
    client: AsyncClient, api_key_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/tasks",
        json={"title": "T", "assignee_id": "00000000-0000-0000-0000-000000000000"},
        headers=api_key_headers,
    )
    assert response.status_code == 404


async def test_activity_lifecycle_and_filters(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    contact = await _contact(client, admin_headers)
    deal = (
        await client.post(
            "/api/v1/deals",
            json={"title": "Pilot", "contact_id": contact["id"]},
            headers=admin_headers,
        )
    ).json()

    call = await client.post(
        "/api/v1/activities",
        json={"type": "call", "subject": "Intro call", "contact_id": contact["id"]},
        headers=admin_headers,
    )
    assert call.status_code == 201, call.text
    assert call.json()["created_by"]["full_name"] == "Ada Admin"
    assert call.json()["occurred_at"] is not None
    await client.post(
        "/api/v1/activities",
        json={
            "type": "meeting",
            "subject": "Demo",
            "body": "Showed reports",
            "deal_id": deal["id"],
        },
        headers=admin_headers,
    )

    async def subjects(query: str) -> list[str]:
        response = await client.get(f"/api/v1/activities?{query}", headers=admin_headers)
        return [activity["subject"] for activity in response.json()["items"]]

    assert await subjects(f"contact_id={contact['id']}") == ["Intro call"]
    assert await subjects(f"deal_id={deal['id']}") == ["Demo"]
    assert await subjects("type=meeting") == ["Demo"]
    assert await subjects("search=reports") == ["Demo"]

    deleted = await client.delete(f"/api/v1/activities/{call.json()['id']}", headers=admin_headers)
    assert deleted.status_code == 204
    assert await subjects(f"contact_id={contact['id']}") == []


async def test_activity_needs_a_contact_or_deal(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/activities", json={"type": "note", "subject": "Orphan"}, headers=admin_headers
    )
    assert response.status_code == 422


async def test_deleting_a_contact_deletes_its_activities(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    contact = await _contact(client, admin_headers)
    activity = (
        await client.post(
            "/api/v1/activities",
            json={"type": "note", "subject": "Note", "contact_id": contact["id"]},
            headers=admin_headers,
        )
    ).json()

    await client.delete(f"/api/v1/contacts/{contact['id']}", headers=admin_headers)

    response = await client.delete(f"/api/v1/activities/{activity['id']}", headers=admin_headers)
    assert response.status_code == 404
