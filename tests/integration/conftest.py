"""Integration test setup.

These tests run against a real PostgreSQL database (`auto_crm_test`, on the same server as
the dev database). It is recreated once per test run and migrated with Alembic;
tables are truncated after every test.
"""

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core import events
from app.core.database import SessionFactory, engine
from app.core.email import get_mailer
from app.core.events import Event
from app.core.storage import get_storage
from app.main import app
from app.modules.users.service import UserService
from app.seed import CRM_TABLES
from tests.conftest import ROOT, TEST_API_KEY, TEST_DB_NAME
from tests.fakes import FakeMailer, FakeStorage


async def _recreate_database() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    conn = await asyncpg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database="postgres",
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Create a fresh test database and run all migrations (incl. seeded stages)."""
    asyncio.run(_recreate_database())
    command.upgrade(Config(toml_file=ROOT / "pyproject.toml"), "head")


SUPER_ADMIN_EMAIL = "root@example.com"
PASSWORD = "s3cret-password"


@pytest.fixture(autouse=True)
async def clean_tables(request: pytest.FixtureRequest) -> AsyncGenerator[None]:
    # Most tests start in a set-up workspace, so sign-ups work.
    if not request.node.get_closest_marker("not_set_up"):
        async with SessionFactory() as session:
            await UserService(session).create_super_admin(
                email=SUPER_ADMIN_EMAIL, password=PASSWORD, full_name="Root"
            )
    yield
    await events.drain()
    async with engine.begin() as conn:
        # Everything except the seeded pipeline stages and Alembic's bookkeeping.
        await conn.execute(text(f"TRUNCATE {CRM_TABLES} CASCADE"))


@pytest.fixture(scope="session", autouse=True)
async def dispose_engine() -> AsyncGenerator[None]:
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def storage() -> Generator[FakeStorage]:
    """Uploaded files go to memory instead of MinIO."""
    fake = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_storage, None)


@pytest.fixture(autouse=True)
def mailer() -> Generator[FakeMailer]:
    """Sent emails are collected in `mailer.outbox` instead of going to Mailpit."""
    fake = FakeMailer()
    app.dependency_overrides[get_mailer] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_mailer, None)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def api_key_headers() -> dict[str, str]:
    return {"X-API-Key": TEST_API_KEY}


async def register_and_login(
    client: AsyncClient, email: str, full_name: str = "Test User"
) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": full_name},
    )
    assert response.status_code == 201, response.text
    return await login(client, email)


async def login(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def super_admin_headers(client: AsyncClient) -> dict[str, str]:
    return await login(client, SUPER_ADMIN_EMAIL)


@pytest.fixture
async def admin_headers(client: AsyncClient, super_admin_headers: dict[str, str]) -> dict[str, str]:
    """Headers for Ada, a team member the super admin made an admin."""
    headers = await register_and_login(client, "admin@example.com", "Ada Admin")
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    response = await client.patch(
        f"/api/v1/users/{me['id']}", json={"role": "admin"}, headers=super_admin_headers
    )
    assert response.status_code == 200, response.text
    return headers


@pytest.fixture
async def member_headers(client: AsyncClient, admin_headers: dict[str, str]) -> dict[str, str]:
    """Headers for a second user (a member). Depends on the admin existing first."""
    return await register_and_login(client, "member@example.com", "Max Member")


@pytest.fixture
def published_events() -> Any:
    """Collects every domain event published during the test as (event, data) tuples."""
    received: list[tuple[Event, dict[str, Any]]] = []

    async def record(event: Event, data: dict[str, Any]) -> None:
        received.append((event, data))

    events.subscribe(record)
    yield received
    events.unsubscribe(record)
