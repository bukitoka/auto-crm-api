from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.shared.utils import today_utc

EVENTS = "/api/v1/calendar/events"


async def test_manage_personal_calendar_events(
    client: AsyncClient, admin_headers: dict[str, str], member_headers: dict[str, str]
) -> None:
    tomorrow = (today_utc() + timedelta(days=1)).isoformat()
    event = {
        "title": "  Call about renewal  ",
        "notes": "Discuss terms",
        "starts_at": f"{tomorrow}T14:00:00+08:00",
        "ends_at": f"{tomorrow}T15:00:00+08:00",
    }
    window = {"start": f"{tomorrow}T06:30:00Z", "end": f"{tomorrow}T12:00:00Z"}
    created = await client.post(EVENTS, json=event, headers=admin_headers)
    assert created.status_code == 201, created.text
    stored = created.json()
    assert stored["title"] == "Call about renewal"
    assert stored["color"] == "teal"
    path = f"{EVENTS}/{stored['id']}"
    assert (await client.get(EVENTS, params=window, headers=admin_headers)).json() == [stored]
    assert (await client.get(EVENTS, params=window, headers=member_headers)).json() == []
    assert (await client.put(path, json=event, headers=member_headers)).status_code == 404
    assert (await client.delete(path, headers=member_headers)).status_code == 404
    invalid = await client.put(
        path, json={**event, "ends_at": event["starts_at"]}, headers=admin_headers
    )
    assert invalid.status_code == 422
    yesterday = (today_utc() - timedelta(days=2)).isoformat()
    past = {
        **event,
        "starts_at": f"{yesterday}T14:00:00+08:00",
        "ends_at": f"{yesterday}T15:00:00+08:00",
    }
    assert (await client.post(EVENTS, json=past, headers=admin_headers)).status_code == 400
    assert (await client.put(path, json=past, headers=admin_headers)).status_code == 400
    updated = await client.put(
        path, json={**event, "title": "Renewal", "color": "violet"}, headers=admin_headers
    )
    assert updated.json()["title"] == "Renewal"
    assert updated.json()["color"] == "violet"
    unchanged = await client.put(path, json=event, headers=admin_headers)
    assert unchanged.json()["color"] == "violet"
    invalid_color = await client.put(path, json={**event, "color": "green"}, headers=admin_headers)
    assert invalid_color.status_code == 422
    assert (await client.delete(path, headers=admin_headers)).status_code == 204
    assert (await client.get(EVENTS, params=window, headers=admin_headers)).json() == []
    assert (
        await client.get(
            EVENTS, params={"start": window["end"], "end": window["start"]}, headers=admin_headers
        )
    ).status_code == 400


async def test_event_time_must_be_in_the_future(
    client: AsyncClient, admin_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 11, 21, 10, 30, tzinfo=UTC)
    monkeypatch.setattr("app.modules.calendar.router.utc_now", lambda: now)
    event = {
        "title": "Renewal call",
        "starts_at": (now + timedelta(minutes=1)).isoformat(),
        "ends_at": (now + timedelta(hours=1)).isoformat(),
    }
    for start in (now, now - timedelta(minutes=1)):
        response = await client.post(
            EVENTS, json={**event, "starts_at": start.isoformat()}, headers=admin_headers
        )
        assert response.status_code == 400
    created = await client.post(EVENTS, json=event, headers=admin_headers)
    assert created.status_code == 201, created.text
    path = f"{EVENTS}/{created.json()['id']}"

    now += timedelta(hours=2)
    response = await client.put(
        path,
        json={**event, "ends_at": (now - timedelta(minutes=1)).isoformat()},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "End time must be in the future"
    notes_only = await client.put(
        path, json={**event, "notes": "Historical notes"}, headers=admin_headers
    )
    assert notes_only.status_code == 200


async def test_follow_up_queue_tracks_missing_next_steps_and_respects_scope(
    client: AsyncClient, admin_headers: dict[str, str], member_headers: dict[str, str]
) -> None:
    async def create(path: str, data: dict) -> str:
        response = await client.post(f"/api/v1/{path}", json=data, headers=admin_headers)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    today = today_utc()
    lead = await create("contacts", {"first_name": "New lead", "status": "lead"})
    stage = (await client.get("/api/v1/pipeline/stages", headers=admin_headers)).json()[0]["id"]
    deal = await create(
        "deals",
        {
            "title": "Renewal",
            "stage_id": stage,
            "expected_close_date": today.isoformat(),
            "contact_id": lead,
        },
    )
    task = await create(
        "tasks", {"title": "Late call", "due_date": (today - timedelta(days=1)).isoformat()}
    )
    url = "/api/v1/dashboard/follow-ups"
    queued = (await client.get(url, headers=admin_headers)).json()
    assert [(row["kind"], row["id"]) for row in queued] == [
        ("task", task),
        ("deal", deal),
        ("lead", lead),
    ]
    assert (await client.get(url, headers=member_headers)).json() == []
    await create("tasks", {"title": "Renewal call", "deal_id": deal, "due_date": today.isoformat()})
    await create("activities", {"type": "call", "subject": "Intro", "contact_id": lead})
    queued = (await client.get(url, headers=admin_headers)).json()
    assert [(row["kind"], row["id"]) for row in queued] == [("task", task)]
