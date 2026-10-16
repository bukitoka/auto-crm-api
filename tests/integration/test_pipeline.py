from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, insert, select, text

from app.core.database import engine
from app.core.events import Event
from app.modules.pipeline.models import PipelineStage

URL = "/api/v1/pipeline/stages"


@pytest.fixture(autouse=True)
async def restore_stages() -> AsyncGenerator[None]:
    """These tests edit the migration-seeded stages, so put them back afterwards."""
    async with engine.connect() as conn:
        saved = [dict(row) for row in (await conn.execute(select(PipelineStage))).mappings()]
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE deals CASCADE"))
        await conn.execute(delete(PipelineStage))
        await conn.execute(insert(PipelineStage), saved)


async def _stages(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = await client.get(URL, headers=headers)
    assert response.status_code == 200
    return response.json()


async def _by_name(client: AsyncClient, headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {stage["name"]: stage for stage in await _stages(client, headers)}


async def test_create_open_stage_goes_before_won_and_lost(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        URL, json={"name": " Demo ", "probability": 55}, headers=super_admin_headers
    )

    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Demo"
    assert response.json()["deal_count"] == 0
    names = [stage["name"] for stage in await _stages(client, admin_headers)]
    assert names == ["Qualification", "Proposal", "Negotiation", "Demo", "Won", "Lost"]


async def test_list_includes_deal_counts(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await client.post("/api/v1/deals", json={"title": "A"}, headers=admin_headers)

    stages = await _by_name(client, admin_headers)

    assert stages["Qualification"]["deal_count"] == 1
    assert stages["Proposal"]["deal_count"] == 0


async def test_create_and_rename_reject_duplicate_names(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    response = await client.post(URL, json={"name": "proposal"}, headers=super_admin_headers)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]

    stages = await _by_name(client, admin_headers)
    response = await client.patch(
        f"{URL}/{stages['Proposal']['id']}", json={"name": "WON"}, headers=super_admin_headers
    )
    assert response.status_code == 409


async def test_rename_and_update_probability(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    stages = await _by_name(client, admin_headers)

    response = await client.patch(
        f"{URL}/{stages['Proposal']['id']}",
        json={"name": "Proposal sent", "probability": 45},
        headers=super_admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Proposal sent"
    assert response.json()["probability"] == 45
    # Changing only the case of its own name is fine.
    response = await client.patch(
        f"{URL}/{stages['Proposal']['id']}",
        json={"name": "proposal SENT"},
        headers=super_admin_headers,
    )
    assert response.status_code == 200


async def test_validation_rules(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    stages = await _by_name(client, admin_headers)

    for body in ({"name": ""}, {"name": "X", "probability": 101}, {"name": "X", "probability": -1}):
        response = await client.post(URL, json=body, headers=super_admin_headers)
        assert response.status_code == 422, body

    response = await client.post(
        URL, json={"name": "Both", "is_won": True, "is_lost": True}, headers=super_admin_headers
    )
    assert response.status_code == 400
    response = await client.patch(
        f"{URL}/{stages['Won']['id']}", json={"is_lost": True}, headers=super_admin_headers
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "A stage can't be both won and lost"
    response = await client.patch(
        f"{URL}/{stages['Won']['id']}", json={"name": None}, headers=super_admin_headers
    )
    assert response.status_code == 422


async def test_marking_stage_won_closes_its_deals(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    stages = await _by_name(client, admin_headers)
    deal = (await client.post("/api/v1/deals", json={"title": "A"}, headers=admin_headers)).json()
    assert deal["closed_at"] is None

    await client.patch(
        f"{URL}/{stages['Qualification']['id']}", json={"is_won": True}, headers=super_admin_headers
    )
    deal = (await client.get(f"/api/v1/deals/{deal['id']}", headers=admin_headers)).json()
    assert deal["closed_at"] is not None

    await client.patch(
        f"{URL}/{stages['Qualification']['id']}",
        json={"is_won": False},
        headers=super_admin_headers,
    )
    deal = (await client.get(f"/api/v1/deals/{deal['id']}", headers=admin_headers)).json()
    assert deal["closed_at"] is None


async def test_reorder(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    ids = [stage["id"] for stage in await _stages(client, admin_headers)]
    new_order = [ids[2], ids[0], ids[1], ids[3], ids[4]]

    response = await client.put(
        f"{URL}/order", json={"stage_ids": new_order}, headers=super_admin_headers
    )

    assert response.status_code == 200, response.text
    assert [stage["id"] for stage in response.json()] == new_order
    assert [stage["position"] for stage in response.json()] == [1, 2, 3, 4, 5]
    assert [stage["id"] for stage in await _stages(client, admin_headers)] == new_order


async def test_reorder_requires_every_stage_once(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    ids = [stage["id"] for stage in await _stages(client, admin_headers)]

    for stage_ids in (ids[:-1], [*ids[:-1], ids[0]]):
        response = await client.put(
            f"{URL}/order", json={"stage_ids": stage_ids}, headers=super_admin_headers
        )
        assert response.status_code == 400


async def test_delete_empty_stage(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    stages = await _by_name(client, admin_headers)

    response = await client.delete(f"{URL}/{stages['Proposal']['id']}", headers=super_admin_headers)

    assert response.status_code == 204
    assert "Proposal" not in await _by_name(client, admin_headers)


async def test_delete_stage_with_deals_moves_them(
    client: AsyncClient,
    admin_headers: dict[str, str],
    published_events: list[tuple[Event, dict[str, Any]]],
    super_admin_headers: dict[str, str],
) -> None:
    stages = await _by_name(client, admin_headers)
    qualification, won = stages["Qualification"]["id"], stages["Won"]["id"]
    deal = (await client.post("/api/v1/deals", json={"title": "A"}, headers=admin_headers)).json()
    published_events.clear()

    response = await client.delete(f"{URL}/{qualification}", headers=super_admin_headers)
    assert response.status_code == 409
    assert "1 deal(s)" in response.json()["detail"]
    response = await client.delete(
        f"{URL}/{qualification}", params={"move_to": qualification}, headers=super_admin_headers
    )
    assert response.status_code == 400

    response = await client.delete(
        f"{URL}/{qualification}", params={"move_to": won}, headers=super_admin_headers
    )

    assert response.status_code == 204
    deal = (await client.get(f"/api/v1/deals/{deal['id']}", headers=admin_headers)).json()
    assert deal["stage"]["name"] == "Won"
    assert deal["closed_at"] is not None
    assert [event for event, _ in published_events] == [Event.DEAL_STAGE_CHANGED, Event.DEAL_WON]


async def test_last_open_stage_is_kept(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    stages = await _by_name(client, admin_headers)
    for name in ("Qualification", "Proposal"):
        response = await client.delete(f"{URL}/{stages[name]['id']}", headers=super_admin_headers)
        assert response.status_code == 204

    last_open = stages["Negotiation"]["id"]
    response = await client.delete(f"{URL}/{last_open}", headers=super_admin_headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "The last open stage can't be deleted"
    response = await client.patch(
        f"{URL}/{last_open}", json={"is_lost": True}, headers=super_admin_headers
    )
    assert response.status_code == 400
    # Won and Lost can still go.
    response = await client.delete(f"{URL}/{stages['Won']['id']}", headers=super_admin_headers)
    assert response.status_code == 204


async def test_unknown_stage_is_404(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    response = await client.patch(
        f"{URL}/{missing}", json={"name": "X"}, headers=super_admin_headers
    )
    assert response.status_code == 404
    response = await client.delete(f"{URL}/{missing}", headers=super_admin_headers)
    assert response.status_code == 404


async def test_members_cannot_edit_the_pipeline(
    client: AsyncClient, member_headers: dict[str, str]
) -> None:
    stages = await _stages(client, member_headers)
    stage_id = stages[0]["id"]

    responses = [
        await client.post(URL, json={"name": "Nope"}, headers=member_headers),
        await client.patch(f"{URL}/{stage_id}", json={"name": "Nope"}, headers=member_headers),
        await client.put(
            f"{URL}/order", json={"stage_ids": [s["id"] for s in stages]}, headers=member_headers
        ),
        await client.delete(f"{URL}/{stage_id}", headers=member_headers),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403, 403]
