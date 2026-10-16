"""Storage and email are the in-memory fakes from `tests/fakes.py` (see conftest)."""

import io
import re

from httpx import AsyncClient
from PIL import Image

from tests.fakes import FakeMailer, FakeStorage


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (800, 400), "teal").save(output, format="PNG")
    return output.getvalue()


def image_file() -> dict:
    return {"file": ("photo.png", png_bytes(), "image/png")}


async def create_contact(client: AsyncClient, headers: dict[str, str], **values: str) -> dict:
    response = await client.post(
        "/api/v1/contacts", json={"first_name": "Jane", **values}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_contact_avatar_upload_and_delete(
    client: AsyncClient, admin_headers: dict[str, str], storage: FakeStorage
) -> None:
    contact = await create_contact(client, admin_headers)
    assert contact["avatar_url"] is None

    uploaded = await client.put(
        f"/api/v1/contacts/{contact['id']}/avatar", files=image_file(), headers=admin_headers
    )
    assert uploaded.status_code == 200, uploaded.text
    assert "X-Amz-Signature" in uploaded.json()["avatar_url"]
    [(key, (data, content_type))] = storage.files.items()
    assert key.startswith(f"contacts/{contact['id']}/")
    assert content_type == "image/webp"
    assert Image.open(io.BytesIO(data)).size == (512, 256)

    removed = await client.delete(f"/api/v1/contacts/{contact['id']}/avatar", headers=admin_headers)
    assert removed.status_code == 200
    assert removed.json()["avatar_url"] is None
    assert storage.files == {}


async def test_invalid_upload_is_rejected(
    client: AsyncClient, admin_headers: dict[str, str], storage: FakeStorage
) -> None:
    contact = await create_contact(client, admin_headers)

    response = await client.put(
        f"/api/v1/contacts/{contact['id']}/avatar",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The file is not a valid image"
    assert storage.files == {}


async def test_upload_requires_auth_and_existing_contact(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    missing = "01a13653-9da7-73cb-8d45-ed41bb1c5691"
    unauthenticated = await client.put(f"/api/v1/contacts/{missing}/avatar", files=image_file())
    assert unauthenticated.status_code == 401

    not_found = await client.put(
        f"/api/v1/contacts/{missing}/avatar", files=image_file(), headers=admin_headers
    )
    assert not_found.status_code == 404


async def test_company_logo_upload_and_delete(
    client: AsyncClient, admin_headers: dict[str, str], storage: FakeStorage
) -> None:
    company = await client.post("/api/v1/companies", json={"name": "Acme"}, headers=admin_headers)
    company_id = company.json()["id"]

    uploaded = await client.put(
        f"/api/v1/companies/{company_id}/logo", files=image_file(), headers=admin_headers
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["logo_url"] is not None

    removed = await client.delete(f"/api/v1/companies/{company_id}/logo", headers=admin_headers)
    assert removed.json()["logo_url"] is None
    await client.put(
        f"/api/v1/companies/{company_id}/logo", files=image_file(), headers=admin_headers
    )

    deleted = await client.delete(f"/api/v1/companies/{company_id}", headers=admin_headers)
    assert deleted.status_code == 204
    assert storage.files == {}  # deleting the company removed its logo


async def test_my_avatar_shows_up_on_owned_records(
    client: AsyncClient, admin_headers: dict[str, str], storage: FakeStorage
) -> None:
    uploaded = await client.put(
        "/api/v1/users/me/avatar", files=image_file(), headers=admin_headers
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["avatar_url"] is not None

    me = await client.get("/api/v1/auth/me", headers=admin_headers)
    assert me.json()["avatar_url"] is not None
    contact = await create_contact(client, admin_headers)
    assert contact["owner"]["avatar_url"] is not None  # nested user refs carry the avatar

    removed = await client.delete("/api/v1/users/me/avatar", headers=admin_headers)
    assert removed.json()["avatar_url"] is None
    assert storage.files == {}


async def test_send_email_to_contact_logs_activity(
    client: AsyncClient, admin_headers: dict[str, str], mailer: FakeMailer
) -> None:
    contact = await create_contact(client, admin_headers, last_name="Doe", email="jane@acme.com")

    response = await client.post(
        "/api/v1/emails",
        json={"contact_id": contact["id"], "subject": "Quick question", "body": "Hi Jane!"},
        headers=admin_headers,
    )

    assert response.status_code == 201, response.text
    activity = response.json()
    assert (activity["type"], activity["subject"]) == ("email", "Quick question")
    assert activity["created_by"]["full_name"] == "Ada Admin"
    [mail] = mailer.outbox
    assert mail.to == "Jane Doe <jane@acme.com>"
    assert mail.reply_to == "Ada Admin <admin@example.com>"

    timeline = await client.get(
        "/api/v1/activities", params={"contact_id": contact["id"]}, headers=admin_headers
    )
    assert [a["type"] for a in timeline.json()["items"]] == ["email"]


async def test_send_email_validation(
    client: AsyncClient, admin_headers: dict[str, str], mailer: FakeMailer
) -> None:
    no_email = await create_contact(client, admin_headers)

    response = await client.post(
        "/api/v1/emails",
        json={"contact_id": no_email["id"], "subject": "Hi", "body": "Hi"},
        headers=admin_headers,
    )
    assert response.status_code == 400

    empty = await client.post(
        "/api/v1/emails",
        json={"contact_id": no_email["id"], "subject": "", "body": "Hi"},
        headers=admin_headers,
    )
    assert empty.status_code == 422
    assert mailer.outbox == []


async def test_password_reset_flow(
    client: AsyncClient, admin_headers: dict[str, str], mailer: FakeMailer
) -> None:
    requested = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "ADMIN@example.com"}
    )
    assert requested.status_code == 202
    [mail] = mailer.outbox
    match = re.search(r"token=(\S+)", mail.text)
    assert match is not None
    token = match.group(1)

    reset = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "a-new-password"}
    )
    assert reset.status_code == 204

    old_login = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "s3cret-password"}
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "a-new-password"}
    )
    assert new_login.status_code == 200

    reused = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "another-password"}
    )
    assert reused.status_code == 400


async def test_forgot_password_for_unknown_email_looks_the_same(
    client: AsyncClient, mailer: FakeMailer
) -> None:
    response = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
    )

    assert response.status_code == 202
    assert "reset link" in response.json()["detail"]
    assert mailer.outbox == []


async def test_notify_sends_to_every_recipient_with_the_api_key(
    client: AsyncClient, api_key_headers: dict[str, str], mailer: FakeMailer
) -> None:
    response = await client.post(
        "/api/v1/emails/notify",
        json={"to": ["a@example.com", "b@example.com"], "subject": "Deal won", "text": "Nice"},
        headers=api_key_headers,
    )

    assert response.status_code == 204, response.text
    assert [mail.to for mail in mailer.outbox] == ["a@example.com", "b@example.com"]


async def test_notify_needs_the_api_key(
    client: AsyncClient, admin_headers: dict[str, str], mailer: FakeMailer
) -> None:
    body = {"to": ["a@example.com"], "subject": "Hi", "text": "Hi"}

    assert (await client.post("/api/v1/emails/notify", json=body)).status_code == 401
    as_admin = await client.post("/api/v1/emails/notify", json=body, headers=admin_headers)
    assert as_admin.status_code == 401
    assert mailer.outbox == []
