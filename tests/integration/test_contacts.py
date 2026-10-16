from typing import Any

from httpx import AsyncClient

from app.core.events import Event


async def test_contact_crud(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    company = await client.post(
        "/api/v1/companies",
        json={"name": "Acme Inc", "industry": "Software"},
        headers=admin_headers,
    )
    assert company.status_code == 201
    company_id = company.json()["id"]

    created = await client.post(
        "/api/v1/contacts",
        json={
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "Jane@Acme.com",
            "company_id": company_id,
            "tags": ["vip"],
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    contact = created.json()
    assert contact["email"] == "jane@acme.com"
    assert contact["status"] == "lead"
    assert contact["company"] == {"id": company_id, "name": "Acme Inc"}
    assert contact["owner"]["full_name"] == "Ada Admin"

    fetched = await client.get(f"/api/v1/contacts/{contact['id']}", headers=admin_headers)
    assert fetched.status_code == 200
    assert fetched.json()["tags"] == ["vip"]

    # Update (and clear the company)
    updated = await client.patch(
        f"/api/v1/contacts/{contact['id']}",
        json={"status": "customer", "company_id": None},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "customer"
    assert updated.json()["company"] is None

    deleted = await client.delete(f"/api/v1/contacts/{contact['id']}", headers=admin_headers)
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/contacts/{contact['id']}", headers=admin_headers)
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Contact not found"}


async def test_list_contacts_with_search_filters_and_pagination(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    for first_name, status in [("Alice", "lead"), ("Bob", "customer"), ("Alina", "lead")]:
        await client.post(
            "/api/v1/contacts",
            json={"first_name": first_name, "status": status},
            headers=admin_headers,
        )

    page = await client.get("/api/v1/contacts?page=1&size=2", headers=admin_headers)
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 2
    assert page.json()["page"] == 1
    assert page.json()["size"] == 2

    found = await client.get("/api/v1/contacts?search=ali&status=lead", headers=admin_headers)
    assert sorted(c["first_name"] for c in found.json()["items"]) == ["Alice", "Alina"]


async def test_duplicate_contact_email_conflicts(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    payload = {"first_name": "Sam", "email": "sam@example.com"}
    assert (await client.post("/api/v1/contacts", json=payload, headers=admin_headers)).is_success
    response = await client.post("/api/v1/contacts", json=payload, headers=admin_headers)
    assert response.status_code == 409


async def test_patch_rejects_null_for_required_field(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    contact = (
        await client.post("/api/v1/contacts", json={"first_name": "Kim"}, headers=admin_headers)
    ).json()
    response = await client.patch(
        f"/api/v1/contacts/{contact['id']}", json={"first_name": None}, headers=admin_headers
    )
    assert response.status_code == 422


async def test_creating_contact_publishes_event(
    client: AsyncClient,
    admin_headers: dict[str, str],
    published_events: list[tuple[Event, dict[str, Any]]],
) -> None:
    await client.post("/api/v1/contacts", json={"first_name": "Eve"}, headers=admin_headers)

    assert [event for event, _ in published_events] == [Event.CONTACT_CREATED]
    assert published_events[0][1]["first_name"] == "Eve"


async def test_integration_lead_requires_api_key(
    client: AsyncClient, admin_headers: dict[str, str], api_key_headers: dict[str, str]
) -> None:
    me = (await client.get("/api/v1/auth/me", headers=admin_headers)).json()
    lead = {
        "owner_id": me["id"],
        "first_name": "Leo",
        "email": "leo@startup.io",
        "company_name": "Startup IO",
        "message": "Please call me back",
    }
    # A user JWT is not enough for this endpoint.
    jwt_attempt = await client.post("/api/v1/integrations/leads", json=lead, headers=admin_headers)
    assert jwt_attempt.status_code == 401

    created = await client.post("/api/v1/integrations/leads", json=lead, headers=api_key_headers)
    assert created.status_code == 201, created.text
    assert created.json()["source"] == "web_form"
    assert created.json()["company"]["name"] == "Startup IO"

    again = await client.post("/api/v1/integrations/leads", json=lead, headers=api_key_headers)
    assert again.status_code == 200
    assert again.json()["id"] == created.json()["id"]

    activities = await client.get(
        f"/api/v1/activities?contact_id={created.json()['id']}", headers=admin_headers
    )
    assert activities.json()["total"] == 2
