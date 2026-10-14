from httpx import AsyncClient


async def test_company_crud(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    created = await client.post(
        "/api/v1/companies",
        json={"name": "Acme Inc", "domain": "acme.com", "industry": "Software"},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    company = created.json()
    assert company["owner"]["full_name"] == "Ada Admin"

    fetched = await client.get(f"/api/v1/companies/{company['id']}", headers=admin_headers)
    assert fetched.json()["domain"] == "acme.com"

    updated = await client.patch(
        f"/api/v1/companies/{company['id']}",
        json={"industry": "Retail", "domain": None},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["industry"] == "Retail"
    assert updated.json()["domain"] is None
    assert updated.json()["name"] == "Acme Inc"

    deleted = await client.delete(f"/api/v1/companies/{company['id']}", headers=admin_headers)
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/companies/{company['id']}", headers=admin_headers)
    assert missing.status_code == 404


async def test_list_companies_filters_by_search_and_industry(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    for name, domain, industry in [
        ("Acme", "acme.com", "Software"),
        ("Globex", "globex.io", "Retail"),
        ("Initech", "initech.com", "Software"),
    ]:
        await client.post(
            "/api/v1/companies",
            json={"name": name, "domain": domain, "industry": industry},
            headers=admin_headers,
        )

    software = await client.get("/api/v1/companies?industry=Software", headers=admin_headers)
    by_domain = await client.get("/api/v1/companies?search=globex.io", headers=admin_headers)

    assert [c["name"] for c in software.json()["items"]] == ["Acme", "Initech"]  # sorted by name
    assert [c["name"] for c in by_domain.json()["items"]] == ["Globex"]


async def test_company_with_unknown_owner_is_404(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/companies",
        json={"name": "Acme", "owner_id": "00000000-0000-0000-0000-000000000000"},
        headers=admin_headers,
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Owner not found"}


async def test_deleting_a_company_keeps_its_contacts(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    company = (
        await client.post("/api/v1/companies", json={"name": "Acme"}, headers=admin_headers)
    ).json()
    contact = (
        await client.post(
            "/api/v1/contacts",
            json={"first_name": "Jane", "company_id": company["id"]},
            headers=admin_headers,
        )
    ).json()

    await client.delete(f"/api/v1/companies/{company['id']}", headers=admin_headers)

    after = await client.get(f"/api/v1/contacts/{contact['id']}", headers=admin_headers)
    assert after.status_code == 200
    assert after.json()["company"] is None
