from httpx import AsyncClient

from tests.integration.conftest import register_and_login


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_first_user_is_admin_and_next_is_member(client: AsyncClient) -> None:
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "First@Example.com", "password": "password123", "full_name": "First"},
    )
    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": "password123", "full_name": "Second"},
    )

    assert first.status_code == 201
    assert first.json()["role"] == "admin"
    assert first.json()["email"] == "first@example.com"
    assert "hashed_password" not in first.json()
    assert second.json()["role"] == "member"


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


async def test_service_account_does_not_take_first_admin_slot(
    client: AsyncClient, api_key_headers: dict[str, str]
) -> None:
    await client.get("/api/v1/auth/me", headers=api_key_headers)  # creates the service account
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "boss@example.com", "password": "password123", "full_name": "Boss"},
    )
    assert response.json()["role"] == "admin"


async def test_only_admins_can_update_users(
    client: AsyncClient, admin_headers: dict[str, str], member_headers: dict[str, str]
) -> None:
    users = (await client.get("/api/v1/users", headers=admin_headers)).json()
    assert users["total"] == 2
    member = next(u for u in users["items"] if u["role"] == "member")

    forbidden = await client.patch(
        f"/api/v1/users/{member['id']}", json={"role": "admin"}, headers=member_headers
    )
    assert forbidden.status_code == 403

    promoted = await client.patch(
        f"/api/v1/users/{member['id']}", json={"role": "admin"}, headers=admin_headers
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"


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
    assert response.json() == {"detail": "You cannot demote or deactivate yourself"}


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
