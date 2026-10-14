from typing import Any

from httpx import AsyncClient

from app.core.events import Event


async def _stages(client: AsyncClient, headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    response = await client.get("/api/v1/pipeline/stages", headers=headers)
    return {stage["name"]: stage for stage in response.json()}


async def test_pipeline_stages_are_seeded_in_order(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/pipeline/stages", headers=admin_headers)
    names = [stage["name"] for stage in response.json()]
    assert names == ["Qualification", "Proposal", "Negotiation", "Won", "Lost"]


async def test_create_deal_defaults_to_first_stage(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/deals", json={"title": "Big deal", "value": "1234.50"}, headers=admin_headers
    )
    assert response.status_code == 201, response.text
    deal = response.json()
    assert deal["value"] == 1234.5
    assert deal["currency"] == "USD"
    assert deal["stage"]["name"] == "Qualification"
    assert deal["contact"] is None
    assert deal["owner"]["full_name"] == "Ada Admin"


async def test_stage_change_to_won_emits_events(
    client: AsyncClient,
    admin_headers: dict[str, str],
    published_events: list[tuple[Event, dict[str, Any]]],
) -> None:
    stages = await _stages(client, admin_headers)
    deal = (
        await client.post(
            "/api/v1/deals", json={"title": "Renewal", "value": 500}, headers=admin_headers
        )
    ).json()
    published_events.clear()  # ignore deal.created

    response = await client.patch(
        f"/api/v1/deals/{deal['id']}/stage",
        json={"stage_id": stages["Won"]["id"]},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["stage"]["is_won"] is True
    assert response.json()["closed_at"] is not None
    assert [event for event, _ in published_events] == [Event.DEAL_STAGE_CHANGED, Event.DEAL_WON]
    stage_changed = published_events[0][1]
    assert stage_changed["previous_stage"]["name"] == "Qualification"
    assert stage_changed["stage"]["name"] == "Won"


async def test_patch_with_stage_id_also_emits_stage_events(
    client: AsyncClient,
    admin_headers: dict[str, str],
    published_events: list[tuple[Event, dict[str, Any]]],
) -> None:
    stages = await _stages(client, admin_headers)
    deal = (await client.post("/api/v1/deals", json={"title": "X"}, headers=admin_headers)).json()
    published_events.clear()

    response = await client.patch(
        f"/api/v1/deals/{deal['id']}",
        json={"title": "X v2", "stage_id": stages["Lost"]["id"]},
        headers=admin_headers,
    )

    assert response.json()["title"] == "X v2"
    assert [event for event, _ in published_events] == [Event.DEAL_STAGE_CHANGED, Event.DEAL_LOST]


async def test_same_stage_does_not_emit(
    client: AsyncClient,
    admin_headers: dict[str, str],
    published_events: list[tuple[Event, dict[str, Any]]],
) -> None:
    deal = (await client.post("/api/v1/deals", json={"title": "Y"}, headers=admin_headers)).json()
    published_events.clear()

    await client.patch(
        f"/api/v1/deals/{deal['id']}/stage",
        json={"stage_id": deal["stage_id"]},
        headers=admin_headers,
    )
    assert published_events == []


async def test_dashboard_summary(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    stages = await _stages(client, admin_headers)
    await client.post("/api/v1/deals", json={"title": "Open", "value": 100}, headers=admin_headers)
    won = (
        await client.post(
            "/api/v1/deals", json={"title": "Won", "value": 40}, headers=admin_headers
        )
    ).json()
    await client.patch(
        f"/api/v1/deals/{won['id']}/stage",
        json={"stage_id": stages["Won"]["id"]},
        headers=admin_headers,
    )
    await client.post("/api/v1/contacts", json={"first_name": "Lead"}, headers=admin_headers)
    await client.post(
        "/api/v1/tasks", json={"title": "Old task", "due_date": "2020-01-01"}, headers=admin_headers
    )

    response = await client.get("/api/v1/dashboard/summary", headers=admin_headers)

    assert response.status_code == 200
    summary = response.json()
    assert summary["open_pipeline_value"] == 100
    assert summary["won_this_month_value"] == 40
    assert summary["new_leads_this_month"] == 1
    assert summary["overdue_tasks"] == 1
    by_stage = {row["stage_name"]: row for row in summary["pipeline_by_stage"]}
    assert by_stage["Qualification"]["deal_count"] == 1
    assert by_stage["Won"]["total_value"] == 40
    assert [task["title"] for task in summary["my_tasks"]] == ["Old task"]


async def test_deal_crud_and_filters(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    stages = await _stages(client, admin_headers)
    company = (
        await client.post("/api/v1/companies", json={"name": "Acme"}, headers=admin_headers)
    ).json()
    contact = (
        await client.post("/api/v1/contacts", json={"first_name": "Jo"}, headers=admin_headers)
    ).json()
    pilot = (
        await client.post(
            "/api/v1/deals",
            json={
                "title": "Acme pilot",
                "contact_id": contact["id"],
                "company_id": company["id"],
                "stage_id": stages["Proposal"]["id"],
            },
            headers=admin_headers,
        )
    ).json()
    await client.post("/api/v1/deals", json={"title": "Other"}, headers=admin_headers)

    async def titles(query: str) -> list[str]:
        response = await client.get(f"/api/v1/deals?{query}", headers=admin_headers)
        return [deal["title"] for deal in response.json()["items"]]

    assert await titles(f"stage_id={stages['Proposal']['id']}") == ["Acme pilot"]
    assert await titles(f"contact_id={contact['id']}") == ["Acme pilot"]
    assert await titles(f"company_id={company['id']}") == ["Acme pilot"]
    assert await titles(f"owner_id={pilot['owner_id']}") == ["Other", "Acme pilot"]
    assert await titles("search=pilot") == ["Acme pilot"]

    fetched = await client.get(f"/api/v1/deals/{pilot['id']}", headers=admin_headers)
    assert fetched.json()["company"]["name"] == "Acme"
    assert fetched.json()["contact"]["first_name"] == "Jo"

    deleted = await client.delete(f"/api/v1/deals/{pilot['id']}", headers=admin_headers)
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/deals/{pilot['id']}", headers=admin_headers)
    assert missing.status_code == 404


async def test_reopening_a_won_deal_clears_closed_at(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    stages = await _stages(client, admin_headers)
    deal = (
        await client.post(
            "/api/v1/deals",
            json={"title": "Z", "stage_id": stages["Won"]["id"]},
            headers=admin_headers,
        )
    ).json()
    assert deal["closed_at"] is not None

    response = await client.patch(
        f"/api/v1/deals/{deal['id']}/stage",
        json={"stage_id": stages["Negotiation"]["id"]},
        headers=admin_headers,
    )

    assert response.json()["closed_at"] is None
