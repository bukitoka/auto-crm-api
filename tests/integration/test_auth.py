import pytest
from httpx import AsyncClient

from tests.integration.conftest import PASSWORD, create_admin_and_login

USERS = "/api/v1/users"


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.not_set_up
async def test_setup_creates_the_super_admin_once(client: AsyncClient) -> None:
    account = {"email": "Owner@Example.com", "password": "password123", "full_name": "Owner"}
    assert (await client.get("/api/v1/auth/setup")).json() == {"needs_setup": True}

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


async def test_public_sign_up_is_closed(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "first@example.com", "password": "password123", "full_name": "First"},
    )

    assert response.status_code in (404, 405)


async def test_super_admin_creates_admins(
    client: AsyncClient, super_admin_headers: dict[str, str]
) -> None:
    payload = {"email": "New@Example.com", "password": "password123", "full_name": "Nina New"}

    created = await client.post(USERS, json=payload, headers=super_admin_headers)

    assert created.status_code == 201
    assert (created.json()["email"], created.json()["role"], created.json()["is_super_admin"]) == (
        "new@example.com",
        "admin",
        False,
    )
    assert "hashed_password" not in created.json()
    login = await client.post(
        "/api/v1/auth/login", json={"email": "new@example.com", "password": "password123"}
    )
    assert login.status_code == 200

    duplicate = await client.post(USERS, json=payload, headers=super_admin_headers)
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "A user with this email already exists"}


async def test_admins_cannot_create_or_manage_accounts(
    client: AsyncClient, admin_headers: dict[str, str], member_headers: dict[str, str]
) -> None:
    payload = {"email": "x@example.com", "password": "password123", "full_name": "X"}
    other = (await client.get("/api/v1/auth/me", headers=member_headers)).json()

    created = await client.post(USERS, json=payload, headers=admin_headers)
    switched_off = await client.patch(
        f"{USERS}/{other['id']}", json={"is_active": False}, headers=admin_headers
    )

    assert (created.status_code, switched_off.status_code) == (403, 403)
    assert switched_off.json() == {"detail": "Only the super admin can do this"}
    assert (await client.get("/api/v1/auth/me", headers=member_headers)).status_code == 200


async def test_super_admin_deactivates_and_reactivates_an_admin(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    me = (await client.get("/api/v1/auth/me", headers=admin_headers)).json()
    url = f"{USERS}/{me['id']}"

    off = await client.patch(url, json={"is_active": False}, headers=super_admin_headers)

    assert off.json()["is_active"] is False
    assert (await client.get("/api/v1/auth/me", headers=admin_headers)).status_code == 401
    login = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD}
    )
    assert login.status_code == 401

    on = await client.patch(url, json={"is_active": True}, headers=super_admin_headers)
    assert on.json()["is_active"] is True
    assert (await client.get("/api/v1/auth/me", headers=admin_headers)).status_code == 200


async def test_roles_cannot_be_changed(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    me = (await client.get("/api/v1/auth/me", headers=admin_headers)).json()

    response = await client.patch(
        f"{USERS}/{me['id']}",
        json={"role": "member", "full_name": "Renamed"},
        headers=super_admin_headers,
    )

    assert response.status_code == 200
    assert (response.json()["role"], response.json()["full_name"]) == ("admin", "Renamed")


async def test_user_lists_follow_the_role(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    super_admin_headers: dict[str, str],
) -> None:
    seen_by_admin = (await client.get(USERS, headers=admin_headers)).json()["items"]
    seen_by_super = (await client.get(USERS, headers=super_admin_headers)).json()["items"]

    assert [u["email"] for u in seen_by_admin] == ["admin@example.com"]
    assert sorted(u["email"] for u in seen_by_super) == ["admin@example.com", "max@example.com"]
    searched = (await client.get(f"{USERS}?search=max", headers=super_admin_headers)).json()
    assert [u["full_name"] for u in searched["items"]] == ["Max Admin"]


async def test_super_admin_is_not_listed_or_editable(
    client: AsyncClient, admin_headers: dict[str, str], super_admin_headers: dict[str, str]
) -> None:
    root = (await client.get("/api/v1/auth/me", headers=super_admin_headers)).json()
    assert (root["is_super_admin"], root["role"]) == (True, "admin")

    hidden = await client.patch(
        f"{USERS}/{root['id']}", json={"is_active": False}, headers=super_admin_headers
    )
    assert hidden.status_code == 404


async def test_login_and_me(client: AsyncClient, super_admin_headers: dict[str, str]) -> None:
    headers = await create_admin_and_login(client, super_admin_headers, "me@example.com", "Me")

    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["full_name"] == "Me"


async def test_login_with_wrong_password(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}


async def test_protected_route_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    bad_token = {"Authorization": "Bearer not-a-token"}
    assert (await client.get("/api/v1/auth/me", headers=bad_token)).status_code == 401


async def test_api_key_authenticates_as_service_account(
    client: AsyncClient, api_key_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/auth/me", headers=api_key_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "automation@auto-crm.local"

    wrong = await client.get("/api/v1/auth/me", headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401


async def test_app_lifespan_starts_and_stops_cleanly() -> None:
    from app.main import app

    async with app.router.lifespan_context(app):
        pass
