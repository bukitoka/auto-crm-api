from typing import Any

from httpx import AsyncClient

from tests.integration.conftest import PASSWORD

API = "/api/v1"


async def _create(client: AsyncClient, path: str, body: dict[str, Any], headers: dict) -> dict:
    response = await client.post(f"{API}/{path}", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_admins_cannot_see_or_change_each_others_records(
    client: AsyncClient, admin_headers: dict[str, str], member_headers: dict[str, str]
) -> None:
    contact = await _create(client, "contacts", {"first_name": "Mine"}, admin_headers)
    company = await _create(client, "companies", {"name": "Mine Inc"}, admin_headers)
    deal = await _create(client, "deals", {"title": "Mine deal"}, admin_headers)
    task = await _create(client, "tasks", {"title": "Mine task"}, admin_headers)

    for path, record in [
        ("contacts", contact),
        ("companies", company),
        ("deals", deal),
        ("tasks", task),
    ]:
        url = f"{API}/{path}/{record['id']}"
        assert (await client.get(url, headers=member_headers)).status_code == 404
        assert (await client.patch(url, json={}, headers=member_headers)).status_code == 404
        assert (await client.delete(url, headers=member_headers)).status_code == 404
        listed = await client.get(f"{API}/{path}", headers=member_headers)
        assert listed.json()["total"] == 0
        assert (await client.get(url, headers=admin_headers)).status_code == 200


async def test_admin_cannot_hand_work_to_another_admin(
    client: AsyncClient, admin_headers: dict[str, str], member_headers: dict[str, str]
) -> None:
    max_id = (await client.get(f"{API}/auth/me", headers=member_headers)).json()["id"]

    task = await client.post(
        f"{API}/tasks", json={"title": "T", "assignee_id": max_id}, headers=admin_headers
    )
    contact = await client.post(
        f"{API}/contacts", json={"first_name": "C", "owner_id": max_id}, headers=admin_headers
    )

    assert task.status_code == 403
    assert contact.status_code == 403


async def test_super_admin_reads_everything_and_writes_nothing(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    contact = await _create(client, "contacts", {"first_name": "Ada's"}, admin_headers)
    deal = await _create(client, "deals", {"title": "Ada deal"}, admin_headers)

    assert (await client.get(f"{API}/contacts", headers=super_admin_headers)).json()["total"] == 1
    assert (await client.get(f"{API}/deals/{deal['id']}", headers=super_admin_headers)).is_success

    writes = [
        client.post(f"{API}/contacts", json={"first_name": "X"}, headers=super_admin_headers),
        client.post(f"{API}/tasks", json={"title": "X"}, headers=super_admin_headers),
        client.post(f"{API}/deals", json={"title": "X"}, headers=super_admin_headers),
        client.post(f"{API}/companies", json={"name": "X"}, headers=super_admin_headers),
        client.patch(
            f"{API}/contacts/{contact['id']}", json={"notes": "x"}, headers=super_admin_headers
        ),
        client.delete(f"{API}/deals/{deal['id']}", headers=super_admin_headers),
    ]
    for request in writes:
        assert (await request).status_code == 403


async def test_only_the_super_admin_manages_admin_accounts(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    body = {"email": "new@example.com", "password": "Passw0rd!long", "full_name": "New Admin"}

    assert (await client.post(f"{API}/users", json=body, headers=admin_headers)).status_code == 403
    created = await client.post(f"{API}/users", json=body, headers=super_admin_headers)
    assert created.status_code == 201
    assert created.json()["role"] == "admin"

    url = f"{API}/users/{created.json()['id']}"
    assert (
        await client.patch(url, json={"is_active": False}, headers=admin_headers)
    ).status_code == 403
    off = await client.patch(url, json={"is_active": False}, headers=super_admin_headers)
    assert off.json()["is_active"] is False

    login = await client.post(
        f"{API}/auth/login", json={"email": body["email"], "password": body["password"]}
    )
    assert login.status_code in (400, 401, 403)


async def test_super_admin_edits_an_admin_account(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    super_admin_headers: dict[str, str],
) -> None:
    users = await client.get(f"{API}/users", headers=super_admin_headers)
    ada = next(u for u in users.json()["items"] if u["email"] == "admin@example.com")
    url = f"{API}/users/{ada['id']}"

    edited = await client.patch(
        url,
        json={
            "full_name": "Ada Lovelace",
            "email": "Ada.L@Example.com",
            "password": "n3w-password!",
        },
        headers=super_admin_headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["full_name"] == "Ada Lovelace"
    assert edited.json()["email"] == "ada.l@example.com"
    assert "password" not in edited.json()

    old = await client.post(
        f"{API}/auth/login", json={"email": "admin@example.com", "password": PASSWORD}
    )
    assert old.status_code in (400, 401)
    new = await client.post(
        f"{API}/auth/login", json={"email": "ada.l@example.com", "password": "n3w-password!"}
    )
    assert new.status_code == 200

    taken = await client.patch(url, json={"email": "max@example.com"}, headers=super_admin_headers)
    assert taken.status_code == 409
    short = await client.patch(url, json={"password": "short"}, headers=super_admin_headers)
    assert short.status_code == 422
    assert (
        await client.patch(url, json={"full_name": "Hacked"}, headers=member_headers)
    ).status_code == 403


async def test_dashboard_is_scoped_to_the_viewer(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    super_admin_headers: dict[str, str],
) -> None:
    await _create(client, "deals", {"title": "Ada", "value": 100}, admin_headers)
    await _create(client, "deals", {"title": "Max", "value": 40}, member_headers)

    async def pipeline(headers: dict[str, str]) -> float:
        summary = (await client.get(f"{API}/dashboard/summary", headers=headers)).json()
        return summary["open_pipeline_value"]

    assert await pipeline(admin_headers) == 100
    assert await pipeline(member_headers) == 40
    assert await pipeline(super_admin_headers) == 140
