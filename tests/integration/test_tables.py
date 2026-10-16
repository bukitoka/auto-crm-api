import csv
import io

from httpx import AsyncClient

from app.core.events import Event


async def _post(client: AsyncClient, path: str, headers: dict[str, str], **data) -> dict:
    response = await client.post(f"/api/v1/{path}", json=data, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _upload(content: str) -> dict:
    return {"file": ("data.csv", content.encode(), "text/csv")}


async def test_contacts_sort_by_name_company_and_status(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    zeta = await _post(client, "companies", admin_headers, name="Zeta")
    acme = await _post(client, "companies", admin_headers, name="acme")
    await _post(client, "contacts", admin_headers, first_name="Bob", status="customer")
    await _post(
        client, "contacts", admin_headers, first_name="alice", company_id=zeta["id"], status="lead"
    )
    await _post(
        client,
        "contacts",
        admin_headers,
        first_name="Carol",
        company_id=acme["id"],
        status="churned",
    )

    async def names(query: str) -> list[str]:
        response = await client.get(f"/api/v1/contacts?{query}", headers=admin_headers)
        assert response.status_code == 200, response.text
        return [c["first_name"] for c in response.json()["items"]]

    assert await names("") == ["Carol", "alice", "Bob"]  # default: newest first
    assert await names("sort=name") == ["alice", "Bob", "Carol"]  # case-insensitive
    assert await names("sort=name&order=desc") == ["Carol", "Bob", "alice"]
    assert await names("sort=company") == ["Carol", "alice", "Bob"]  # no company last
    assert await names("sort=company&order=desc") == ["alice", "Carol", "Bob"]
    assert await names("sort=status") == ["alice", "Bob", "Carol"]  # lifecycle order
    assert await names("sort=ai_score&size=2") == ["Bob", "alice"]  # all empty: ties by id
    assert await names("sort=created_at") == ["Bob", "alice", "Carol"]
    assert await names("sort=created_at&order=desc") == ["Carol", "alice", "Bob"]
    # Ties are broken by id, so paging through a sorted list is stable.


async def test_unknown_sort_field_is_rejected(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    for path in ["contacts", "companies", "deals", "tasks"]:
        response = await client.get(f"/api/v1/{path}?sort=password", headers=admin_headers)
        assert response.status_code == 422, path
    response = await client.get("/api/v1/contacts?sort=name&order=up", headers=admin_headers)
    assert response.status_code == 422


async def test_companies_sort_by_industry_and_created_at(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await _post(client, "companies", admin_headers, name="Acme", industry="Retail")
    await _post(client, "companies", admin_headers, name="Globex")
    await _post(client, "companies", admin_headers, name="Initech", industry="banking")

    async def names(query: str) -> list[str]:
        response = await client.get(f"/api/v1/companies?{query}", headers=admin_headers)
        return [c["name"] for c in response.json()["items"]]

    assert await names("") == ["Acme", "Globex", "Initech"]
    assert await names("sort=industry") == ["Initech", "Acme", "Globex"]
    assert await names("sort=industry&order=desc") == ["Acme", "Initech", "Globex"]
    assert await names("sort=created_at&order=desc") == ["Initech", "Globex", "Acme"]


async def test_deals_sort_by_value_and_stage(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    stages = (await client.get("/api/v1/pipeline/stages", headers=admin_headers)).json()
    first, second = stages[0], stages[1]
    await _post(client, "deals", admin_headers, title="Big", value=900, stage_id=first["id"])
    await _post(client, "deals", admin_headers, title="Small", value=10, stage_id=second["id"])
    await _post(client, "deals", admin_headers, title="Mid", value=300, stage_id=second["id"])

    async def titles(query: str) -> list[str]:
        response = await client.get(f"/api/v1/deals?{query}", headers=admin_headers)
        assert response.status_code == 200, response.text
        return [d["title"] for d in response.json()["items"]]

    assert await titles("sort=value") == ["Small", "Mid", "Big"]
    assert await titles("sort=value&order=desc") == ["Big", "Mid", "Small"]
    assert (await titles("sort=stage"))[0] == "Big"
    assert (await titles("sort=stage&order=desc"))[-1] == "Big"
    assert await titles("sort=title") == ["Big", "Mid", "Small"]
    assert await titles("sort=created_at&order=desc") == ["Mid", "Small", "Big"]


async def test_deals_sort_by_expected_close_date_puts_empty_dates_last(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await _post(client, "deals", admin_headers, title="Late", expected_close_date="2026-09-01")
    await _post(client, "deals", admin_headers, title="Open")
    await _post(client, "deals", admin_headers, title="Soon", expected_close_date="2026-02-01")

    async def titles(query: str) -> list[str]:
        response = await client.get(f"/api/v1/deals?{query}", headers=admin_headers)
        assert response.status_code == 200, response.text
        return [d["title"] for d in response.json()["items"]]

    assert await titles("sort=expected_close_date") == ["Soon", "Late", "Open"]
    assert await titles("sort=expected_close_date&order=desc") == ["Late", "Soon", "Open"]


async def test_tasks_sort_by_priority_and_due_date(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await _post(client, "tasks", admin_headers, title="A", priority="high", due_date="2026-03-01")
    await _post(client, "tasks", admin_headers, title="B", priority="low")
    await _post(client, "tasks", admin_headers, title="C", priority="medium", due_date="2026-01-01")

    async def titles(query: str) -> list[str]:
        response = await client.get(f"/api/v1/tasks?{query}", headers=admin_headers)
        assert response.status_code == 200, response.text
        return [t["title"] for t in response.json()["items"]]

    assert await titles("sort=priority") == ["B", "C", "A"]
    assert await titles("sort=priority&order=desc") == ["A", "C", "B"]
    assert await titles("sort=due_date") == ["C", "A", "B"]  # no date last
    assert await titles("sort=due_date&order=desc") == ["A", "C", "B"]  # no date last
    assert await titles("sort=created_at") == ["A", "B", "C"]
    assert await titles("sort=created_at&order=desc") == ["C", "B", "A"]


async def test_export_contacts_honors_filters_and_sort(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    acme = await _post(client, "companies", admin_headers, name="Acme")
    await _post(
        client,
        "contacts",
        admin_headers,
        first_name="Jane",
        last_name="Doe",
        email="jane@acme.com",
        tags=["vip", "east"],
        company_id=acme["id"],
    )
    await _post(client, "contacts", admin_headers, first_name="Adam", status="customer")
    await _post(client, "contacts", admin_headers, first_name="Zed", status="customer")

    response = await client.get(
        "/api/v1/contacts/export?status=customer&sort=name&order=desc", headers=admin_headers
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="contacts.csv"' in response.headers["content-disposition"]
    assert [r["first_name"] for r in _rows(response.text)] == ["Zed", "Adam"]

    jane = _rows((await client.get("/api/v1/contacts/export", headers=admin_headers)).text)[-1]
    assert jane["email"] == "jane@acme.com"
    assert jane["tags"] == "vip; east"
    assert jane["company"] == "Acme"
    assert jane["owner"] == "Ada Admin"
    assert jane["ai_score"] == ""
    owner_id = (await client.get("/api/v1/auth/me", headers=admin_headers)).json()["id"]
    mine = await client.get(f"/api/v1/contacts/export?owner_id={owner_id}", headers=admin_headers)
    assert len(_rows(mine.text)) == 3


async def test_export_companies_deals_and_tasks(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    acme = await _post(client, "companies", admin_headers, name="Acme", industry="Software")
    contact = await _post(client, "contacts", admin_headers, first_name="Jane", last_name="Doe")
    deal = await _post(
        client,
        "deals",
        admin_headers,
        title="Renewal",
        value=1200.5,
        contact_id=contact["id"],
        company_id=acme["id"],
    )
    await _post(client, "tasks", admin_headers, title="Call", deal_id=deal["id"], priority="high")

    companies = _rows((await client.get("/api/v1/companies/export", headers=admin_headers)).text)
    deals = _rows((await client.get("/api/v1/deals/export", headers=admin_headers)).text)
    tasks = _rows((await client.get("/api/v1/tasks/export", headers=admin_headers)).text)

    assert companies[0]["industry"] == "Software"
    assert deals[0]["value"] == "1200.50"
    assert deals[0]["contact"] == "Jane Doe"
    assert deals[0]["company"] == "Acme"
    assert deals[0]["stage"] == deal["stage"]["name"]
    assert tasks[0]["deal"] == "Renewal"
    assert tasks[0]["priority"] == "high"
    assert tasks[0]["assignee"] == "Ada Admin"
    done = await client.get("/api/v1/tasks/export?open=false", headers=admin_headers)
    assert _rows(done.text) == []


async def test_export_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/contacts/export")
    assert response.status_code == 401


async def test_import_contacts_links_companies_and_skips_bad_rows(
    client: AsyncClient, admin_headers: dict[str, str], published_events: list
) -> None:
    acme = await _post(client, "companies", admin_headers, name="Acme Inc")
    await _post(client, "contacts", admin_headers, first_name="Old", email="taken@example.com")
    content = (
        "First Name,last_name,email,status,tags,company,ai_score\n"
        "Jane,Doe,JANE@example.com,prospect,vip; east,acme inc,99\n"
        "Bob,,,,,Unknown Co,\n"
        ",,,,,,\n"  # blank row: ignored
        "Dup,,taken@example.com,,,,\n"
        "Bad,,not-an-email,,,,\n"
        ",NoFirstName,,,,,\n"
        "Odd,,,weird,,,\n"
    )

    response = await client.post(
        "/api/v1/contacts/import", files=_upload(content), headers=admin_headers
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created"] == 2
    assert result["skipped"] == 4
    assert [e["row"] for e in result["errors"]] == [5, 6, 7, 8]
    assert result["errors"][0]["message"] == "A contact with this email already exists"
    assert result["errors"][1]["message"].startswith("email:")
    assert result["errors"][2]["message"].startswith("first_name:")

    contacts = (await client.get("/api/v1/contacts?sort=name", headers=admin_headers)).json()
    jane = next(c for c in contacts["items"] if c["first_name"] == "Jane")
    bob = next(c for c in contacts["items"] if c["first_name"] == "Bob")
    assert jane["email"] == "jane@example.com"
    assert jane["status"] == "prospect"
    assert jane["tags"] == ["vip", "east"]
    assert jane["company_id"] == acme["id"]
    assert jane["ai_score"] is None  # export-only column, ignored
    assert jane["owner"]["full_name"] == "Ada Admin"
    assert bob["company_id"] is None
    created = [data for event, data in published_events if event == Event.CONTACT_CREATED]
    assert len(created) == 3  # "Old" + the two imported contacts


async def test_contacts_export_can_be_imported_again(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await _post(client, "contacts", admin_headers, first_name="Jane", email="jane@example.com")
    exported = (await client.get("/api/v1/contacts/export", headers=admin_headers)).text

    response = await client.post(
        "/api/v1/contacts/import", files=_upload(exported), headers=admin_headers
    )

    assert response.json()["created"] == 0
    assert response.json()["skipped"] == 1  # same email


async def test_import_companies_skips_existing_names(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await _post(client, "companies", admin_headers, name="Acme")
    content = (
        "name,domain,industry,owner\nACME,acme.com,,\nGlobex,globex.io,Retail,Someone\n,x.com,,\n"
    )

    response = await client.post(
        "/api/v1/companies/import", files=_upload(content), headers=admin_headers
    )

    assert response.json() == {
        "created": 1,
        "skipped": 2,
        "errors": [
            {"row": 2, "message": "A company with this name already exists"},
            {"row": 4, "message": "name: Field required"},
        ],
    }
    companies = (await client.get("/api/v1/companies", headers=admin_headers)).json()["items"]
    assert [c["name"] for c in companies] == ["Acme", "Globex"]
    assert companies[1]["industry"] == "Retail"


async def test_import_caps_the_error_list(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    content = "name,domain\n" + ",x.com\n" * 60

    result = (
        await client.post("/api/v1/companies/import", files=_upload(content), headers=admin_headers)
    ).json()

    assert result["skipped"] == 60
    assert len(result["errors"]) == 50


async def test_import_rejects_empty_large_and_binary_files(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    empty = await client.post("/api/v1/contacts/import", files=_upload(""), headers=admin_headers)
    large = await client.post(
        "/api/v1/contacts/import",
        files=_upload("first_name\n" + "x" * (2 * 1024 * 1024)),
        headers=admin_headers,
    )
    binary = await client.post(
        "/api/v1/contacts/import",
        files={"file": ("data.csv", b"\xff\xfe\x00bad", "text/csv")},
        headers=admin_headers,
    )

    assert empty.status_code == 400
    assert empty.json() == {"detail": "The CSV file is empty"}
    assert large.status_code == 413
    assert binary.status_code == 400


def test_csv_cells_are_safe_from_formula_injection() -> None:
    from app.shared.csv_files import to_csv

    content = to_csv(["a", "b", "c", "d"], [["=HYPERLINK(1)", "+1 555 0100", "-12.5", "@sum"]])
    assert content.splitlines()[1] == "'=HYPERLINK(1),+1 555 0100,-12.5,'@sum"


async def test_escaped_cells_import_unchanged(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    csv_text = "first_name,job_title\nEve,'=Head of Sales\n"
    response = await client.post(
        "/api/v1/contacts/import",
        files={"file": ("c.csv", csv_text, "text/csv")},
        headers=admin_headers,
    )
    assert response.json()["created"] == 1
    page = (await client.get("/api/v1/contacts?search=Eve", headers=admin_headers)).json()
    assert page["items"][0]["job_title"] == "=Head of Sales"
