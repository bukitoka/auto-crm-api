import pytest
from httpx import AsyncClient

from tests.integration.conftest import register_and_login


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.not_set_up
async def test_setup_creates_the_super_admin_once(client: AsyncClient) -> None:
    account = {"email": "Owner@Example.com", "password": "password123", "full_name": "Owner"}
    assert (await client.get("/api/v1/auth/setup")).json() == {"needs_setup": True}
    early = await client.post("/api/v1/auth/register", json=account)
    assert early.status_code == 403

    created = await client.post("/api/v1/auth/setup", json=account)
    again = await client.post("/api/v1/auth/setup", json=account | {"email": "x@example.com"})

    assert created.status_code == 201
    assert (created.json()["email"], created.json()["is_super_admin"]) == (
        "owner@example.com",
        True,
    )
    assert (await client.get("/api/v1/auth/setup")).json() == {"needs_setup": False}
    assert again.status_code == 409
    assert again.json() == {"detail": "The workspace is already set up"}


async def test_sign_ups_become_members(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "First@Example.com", "password": "password123", "full_name": "First"},
    )

    assert response.status_code == 201
    assert (response.json()["role"], response.json()["is_super_admin"]) == ("member", False)
    assert response.json()["email"] == "first@example.com"
    assert "hashed_password" not in response.json()


async def test_register_duplicate_email_conflicts(client: AsyncClient) -> None:
    payload = {"email": "dup@example.com", "password": "password123", "full_name": "Dup"}
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201

    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json() == {"detail": "A user with this email already exists"}


async def test_login_and_me(client: AsyncClient) -> None:
    headers = await register_and_login(client, "me@example.com", "Me Myself")

    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["full_name"] == "Me Myself"


async def test_login_with_wrong_password(client: AsyncClient) -> None:
    await register_and_login(client, "user@example.com")
    response = await client.post(
        "/api/v1/auth/login", json={"email": "user@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}


async def test_protected_route_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    bad_token = {"Authorization": "Bearer not-a-jwt"}
    assert (await client.get("/api/v1/auth/me", headers=bad_token)).status_code == 401


async def test_api_key_authenticates_as_service_account(
    client: AsyncClient, api_key_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/auth/me", headers=api_key_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "automation@auto-crm.local"

    wrong = await client.get("/api/v1/auth/me", headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401


async def test_only_super_admins_can_make_admins(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    super_admin_headers: dict[str, str],
) -> None:
    users = (await client.get("/api/v1/users", headers=admin_headers)).json()
    assert users["total"] == 2
    member = next(u for u in users["items"] if u["role"] == "member")
    url = f"/api/v1/users/{member['id']}"

    by_member = await client.patch(url, json={"role": "admin"}, headers=member_headers)
    by_admin = await client.patch(url, json={"role": "admin"}, headers=admin_headers)
    assert (by_member.status_code, by_admin.status_code) == (403, 403)

    promoted = await client.patch(url, json={"role": "admin"}, headers=super_admin_headers)
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"


async def test_admins_manage_members_but_not_admins(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    super_admin_headers: dict[str, str],
) -> None:
    await register_and_login(client, "other@example.com", "Olga Other")
    users = (await client.get("/api/v1/users", headers=admin_headers)).json()["items"]
    url = {u["email"]: f"/api/v1/users/{u['id']}" for u in users}
    # The super admin makes Max an admin; Max can then use admin routes.
    await client.patch(
        url["member@example.com"], json={"role": "admin"}, headers=super_admin_headers
    )
    assert (await client.get("/api/v1/webhooks", headers=member_headers)).status_code == 200

    deactivate_member = await client.patch(
        url["other@example.com"], json={"is_active": False}, headers=member_headers
    )
    grant_admin = await client.patch(
        url["other@example.com"], json={"role": "admin"}, headers=member_headers
    )
    demote_admin = await client.patch(
        url["admin@example.com"], json={"role": "member"}, headers=member_headers
    )

    assert deactivate_member.status_code == 200
    assert grant_admin.status_code == 403
    assert demote_admin.status_code == 403
    assert demote_admin.json() == {"detail": "Only the super admin can manage admins"}


async def test_super_admins_are_not_part_of_the_team(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    root = (await client.get("/api/v1/auth/me", headers=super_admin_headers)).json()
    assert (root["is_super_admin"], root["role"]) == (True, "admin")

    for headers in (admin_headers, super_admin_headers):
        users = (await client.get("/api/v1/users", headers=headers)).json()["items"]
        assert [u["email"] for u in users] == ["admin@example.com"]
    hidden = await client.patch(
        f"/api/v1/users/{root['id']}", json={"is_active": False}, headers=admin_headers
    )
    assert hidden.status_code == 404
    # The super admin has every admin permission.
    assert (await client.get("/api/v1/webhooks", headers=super_admin_headers)).status_code == 200
    summary = (await client.get("/api/v1/dashboard/summary", headers=super_admin_headers)).json()
    assert [row["user"]["full_name"] for row in summary["team"]] == ["Ada Admin"]


async def test_users_search(
    client: AsyncClient, admin_headers: dict[str, str], member_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/users?search=max", headers=member_headers)

    assert [user["full_name"] for user in response.json()["items"]] == ["Max Member"]


async def test_admin_cannot_demote_self(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    me = (await client.get("/api/v1/auth/me", headers=admin_headers)).json()

    response = await client.patch(
        f"/api/v1/users/{me['id']}", json={"role": "member"}, headers=admin_headers
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "You cannot change your own role or deactivate yourself"}


async def test_deactivated_user_cannot_use_their_token(
    client: AsyncClient, admin_headers: dict[str, str], member_headers: dict[str, str]
) -> None:
    member = (await client.get("/api/v1/auth/me", headers=member_headers)).json()

    await client.patch(
        f"/api/v1/users/{member['id']}", json={"is_active": False}, headers=admin_headers
    )

    assert (await client.get("/api/v1/auth/me", headers=member_headers)).status_code == 401


async def test_app_lifespan_starts_and_stops_cleanly() -> None:
    from app.main import app

    async with app.router.lifespan_context(app):
        pass
