"""The assistant over HTTP: saved conversations, and a scripted AI that "calls" tools for real."""

import json
from collections.abc import Callable
from typing import Any, ClassVar

import pytest
from httpx import AsyncClient
from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_message_tool_call import Function
from pydantic import BaseModel

from app.core.exceptions import AIResponseError
from app.main import app
from app.modules.ai.dependencies import get_ai_client
from app.modules.ai.schemas import EmailDraft, ExtractedContact, LeadScore, TimelineSummary
from app.modules.assistant.service import MAX_STEPS
from tests.fakes import FakeMailer
from tests.integration.conftest import register_and_login

URL = "/api/v1/assistant/conversations"
Step = Callable[[list[dict[str, Any]]], ChatCompletionMessage]


def calls(*tool_calls: tuple[str, dict[str, Any]]) -> Step:
    """A model turn that requests these tool calls."""

    def step(_: list[dict[str, Any]]) -> ChatCompletionMessage:
        return ChatCompletionMessage(
            role="assistant",
            content=None,
            tool_calls=[
                ChatCompletionMessageToolCall(
                    id=f"call_{i}",
                    type="function",
                    function=Function(name=name, arguments=json.dumps(args)),
                )
                for i, (name, args) in enumerate(tool_calls)
            ],
        )

    return step


def says(text: str) -> Step:
    return lambda _: ChatCompletionMessage(role="assistant", content=text)


def fails(_: list[dict[str, Any]]) -> ChatCompletionMessage:
    raise AIResponseError()


class ScriptedAI:
    """Plays back model turns in order and records every request it received."""

    JSON_ANSWERS: ClassVar[dict[type, BaseModel]] = {
        LeadScore: LeadScore(score=77, reasoning="Engaged."),
        TimelineSummary: TimelineSummary(summary="Going well.", next_actions=["Call"]),
        EmailDraft: EmailDraft(subject="Hi", body="Hello Sam"),
        ExtractedContact: ExtractedContact(first_name="Dana", last_name="Lee"),
    }

    def __init__(self) -> None:
        self.script: list[Step] = []
        self.requests: list[list[dict[str, Any]]] = []

    async def chat(self, *, messages: list[dict[str, Any]], tools: list[dict[str, Any]], **_: Any):
        self.requests.append(list(messages))
        step = self.script.pop(0) if self.script else calls(("list_pipeline_stages", {}))
        return step(messages)

    async def complete_json(self, *, schema: type, **_: Any):  # AI features used by tools
        return self.JSON_ANSWERS[schema]

    def tool_results(self, request: int = -1) -> list[dict[str, Any]]:
        return [json.loads(m["content"]) for m in self.requests[request] if m.get("role") == "tool"]


@pytest.fixture
def ai() -> Any:
    fake = ScriptedAI()
    app.dependency_overrides[get_ai_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_ai_client, None)


def message(text: str, context: dict | None = None) -> dict[str, Any]:
    return {"content": text, "context": context}


async def start(client: AsyncClient, headers: dict[str, str], text: str = "Hi") -> dict:
    response = await client.post(URL, json=message(text), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- Conversations ---


async def test_conversation_is_saved_and_continued(
    client: AsyncClient, admin_headers: dict[str, str], ai: ScriptedAI
) -> None:
    ai.script = [says("Hello! How can I help?"), says("Sure, noted.")]

    turn = await start(client, admin_headers, "Hi there, what can you do for me today?")

    conversation = turn["conversation"]
    assert conversation["title"] == "Hi there, what can you do for me today?"
    assert conversation["message_count"] == 2
    assert [(m["role"], m["content"]) for m in turn["messages"]] == [
        ("user", "Hi there, what can you do for me today?"),
        ("assistant", "Hello! How can I help?"),
    ]

    second = await client.post(
        f"{URL}/{conversation['id']}/messages", json=message("Remember X"), headers=admin_headers
    )
    assert second.status_code == 200
    assert second.json()["conversation"]["message_count"] == 4
    # The model saw the earlier messages.
    assert [m["role"] for m in ai.requests[1]] == ["system", "user", "assistant", "user"]

    detail = (await client.get(f"{URL}/{conversation['id']}", headers=admin_headers)).json()
    assert [m["content"] for m in detail["messages"]] == [
        "Hi there, what can you do for me today?",
        "Hello! How can I help?",
        "Remember X",
        "Sure, noted.",
    ]


async def test_long_first_message_makes_a_short_title(
    client: AsyncClient, admin_headers: dict[str, str], ai: ScriptedAI
) -> None:
    ai.script = [says("ok")]
    text = "Please create follow up tasks for every lead that came in from the web form this week"

    turn = await start(client, admin_headers, text)

    assert (
        turn["conversation"]["title"]
        == "Please create follow up tasks for every lead that came in…"
    )


async def test_rename_archive_list_and_delete(
    client: AsyncClient, admin_headers: dict[str, str], ai: ScriptedAI
) -> None:
    ai.script = [says("a"), says("b")]
    first = (await start(client, admin_headers, "First"))["conversation"]
    second = (await start(client, admin_headers, "Second chat"))["conversation"]

    renamed = await client.patch(
        f"{URL}/{first['id']}",
        json={"title": "Renamed", "is_archived": True},
        headers=admin_headers,
    )
    assert renamed.json()["title"] == "Renamed"
    assert renamed.json()["is_archived"] is True

    active = (await client.get(URL, headers=admin_headers)).json()
    archived = (await client.get(URL, params={"archived": True}, headers=admin_headers)).json()
    assert [c["id"] for c in active["items"]] == [second["id"]]
    assert [c["title"] for c in archived["items"]] == ["Renamed"]
    found = (await client.get(URL, params={"search": "second"}, headers=admin_headers)).json()
    assert found["total"] == 1

    deleted = await client.delete(f"{URL}/{second['id']}", headers=admin_headers)
    assert deleted.status_code == 204
    assert (await client.get(f"{URL}/{second['id']}", headers=admin_headers)).status_code == 404


async def test_sending_to_an_archived_chat_brings_it_back(
    client: AsyncClient, admin_headers: dict[str, str], ai: ScriptedAI
) -> None:
    ai.script = [says("a"), says("b")]
    chat = (await start(client, admin_headers))["conversation"]
    await client.patch(f"{URL}/{chat['id']}", json={"is_archived": True}, headers=admin_headers)

    turn = await client.post(
        f"{URL}/{chat['id']}/messages", json=message("Again"), headers=admin_headers
    )

    assert turn.json()["conversation"]["is_archived"] is False


async def test_privacy_and_admin_management(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    ai: ScriptedAI,
) -> None:
    ai.script = [says("a"), says("b")]
    mine = (await start(client, member_headers, "Member chat"))["conversation"]
    admins = (await start(client, admin_headers, "Admin chat"))["conversation"]
    other = await register_and_login(client, "other@example.com", "Olga Other")

    # Members only see (and touch) their own chats.
    assert (await client.get(URL, headers=member_headers)).json()["total"] == 1
    assert (await client.get(f"{URL}/{admins['id']}", headers=member_headers)).status_code == 404
    assert (await client.get(f"{URL}/{mine['id']}", headers=other)).status_code == 404
    assert (await client.delete(f"{URL}/{mine['id']}", headers=other)).status_code == 404
    everyone_as_member = await client.get(URL, params={"scope": "all"}, headers=member_headers)
    assert everyone_as_member.status_code == 403

    # Admins see everyone's, can filter by user, and manage them...
    everyone = (await client.get(URL, params={"scope": "all"}, headers=admin_headers)).json()
    assert {c["user"]["full_name"] for c in everyone["items"]} == {"Ada Admin", "Max Member"}
    only_member = await client.get(
        URL, params={"scope": "all", "user_id": mine["user_id"]}, headers=admin_headers
    )
    assert [c["title"] for c in only_member.json()["items"]] == ["Member chat"]
    assert (await client.get(f"{URL}/{mine['id']}", headers=admin_headers)).status_code == 200

    # ...but cannot post in someone else's conversation.
    speak = await client.post(
        f"{URL}/{mine['id']}/messages", json=message("Hi"), headers=admin_headers
    )
    assert speak.status_code == 403

    archived = await client.patch(
        f"{URL}/{mine['id']}", json={"is_archived": True}, headers=admin_headers
    )
    assert archived.json()["is_archived"] is True


async def test_bulk_actions(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    ai: ScriptedAI,
) -> None:
    ai.script = [says("a"), says("b"), says("c")]
    a = (await start(client, member_headers, "A"))["conversation"]["id"]
    b = (await start(client, member_headers, "B"))["conversation"]["id"]
    c = (await start(client, admin_headers, "C"))["conversation"]["id"]

    # A member can only affect their own conversations.
    archived = await client.post(
        f"{URL}/bulk", json={"ids": [a, c], "action": "archive"}, headers=member_headers
    )
    assert archived.json() == {"affected": 1}
    restored = await client.post(
        f"{URL}/bulk", json={"ids": [a], "action": "unarchive"}, headers=member_headers
    )
    assert restored.json() == {"affected": 1}

    # An admin can delete anyone's.
    deleted = await client.post(
        f"{URL}/bulk", json={"ids": [a, b, c], "action": "delete"}, headers=admin_headers
    )
    assert deleted.json() == {"affected": 3}
    everyone = (await client.get(URL, params={"scope": "all"}, headers=admin_headers)).json()
    assert everyone["total"] == 0


async def test_failed_first_reply_leaves_no_empty_chat(
    client: AsyncClient, admin_headers: dict[str, str], ai: ScriptedAI
) -> None:
    ai.script = [fails]

    response = await client.post(URL, json=message("Hi"), headers=admin_headers)

    assert response.status_code == 502
    assert (await client.get(URL, headers=admin_headers)).json()["total"] == 0


async def test_failed_reply_stores_nothing(
    client: AsyncClient, admin_headers: dict[str, str], ai: ScriptedAI
) -> None:
    ai.script = [says("first"), fails]
    chat = (await start(client, admin_headers))["conversation"]

    response = await client.post(
        f"{URL}/{chat['id']}/messages", json=message("Again"), headers=admin_headers
    )

    assert response.status_code == 502
    detail = (await client.get(f"{URL}/{chat['id']}", headers=admin_headers)).json()
    assert detail["message_count"] == 2


async def test_chat_management_works_without_an_ai_key(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    assert (await client.get(URL, headers=admin_headers)).status_code == 200
    assert (await client.post(URL, json=message("Hi"), headers=admin_headers)).status_code == 503


async def test_request_validation(
    client: AsyncClient, admin_headers: dict[str, str], ai: Any
) -> None:
    assert (await client.post(URL, json={"content": ""}, headers=admin_headers)).status_code == 422
    assert (await client.post(URL, json=message("Hi"))).status_code == 401
    bulk = await client.post(
        f"{URL}/bulk", json={"ids": [], "action": "delete"}, headers=admin_headers
    )
    assert bulk.status_code == 422


# --- Tools ---


async def test_follow_up_creates_task_and_note(
    client: AsyncClient, admin_headers: dict[str, str], ai: ScriptedAI
) -> None:
    contact = (
        await client.post(
            "/api/v1/contacts",
            json={"first_name": "Jane", "last_name": "Doe"},
            headers=admin_headers,
        )
    ).json()
    ai.script = [
        calls(("search_contacts", {"query": "Jane"})),
        calls(
            (
                "create_task",
                {"title": "Send pricing", "due_date": "2026-01-16", "contact_id": contact["id"]},
            ),
            (
                "log_activity",
                {"type": "note", "subject": "Asked for pricing", "contact_id": contact["id"]},
            ),
        ),
        says("Done! I created the follow-up and logged a note."),
    ]

    response = await client.post(
        URL,
        json=message("Follow up with Jane tomorrow", {"type": "contact", "id": contact["id"]}),
        headers=admin_headers,
    )

    assert response.status_code == 201, response.text
    reply = response.json()["messages"][1]
    assert reply["content"] == "Done! I created the follow-up and logged a note."
    assert [(a["kind"], a["entity"]) for a in reply["actions"]] == [
        ("created", "task"),
        ("logged", "activity"),
    ]
    assert reply["actions"][0]["label"] == "Task: Send pricing (due Jan 16)"
    assert reply["actions"][0]["link_id"] == contact["id"]

    # Actions are stored with the message.
    chat_id = response.json()["conversation"]["id"]
    saved = (await client.get(f"{URL}/{chat_id}", headers=admin_headers)).json()
    assert saved["messages"][1]["actions"] == reply["actions"]

    assert ai.tool_results(1)[0]["contacts"][0]["name"] == "Jane Doe"
    assert f"this contact (id {contact['id']})" in ai.requests[0][0]["content"]
    tasks = (await client.get("/api/v1/tasks", headers=admin_headers)).json()["items"]
    assert [(t["title"], t["assignee"]["full_name"]) for t in tasks] == [
        ("Send pricing", "Ada Admin")
    ]


async def test_every_tool_runs_against_the_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    ai: ScriptedAI,
    mailer: FakeMailer,
) -> None:
    company = (
        await client.post("/api/v1/companies", json={"name": "Globex"}, headers=admin_headers)
    ).json()
    contact = (
        await client.post(
            "/api/v1/contacts",
            json={
                "first_name": "Sam",
                "email": "sam@globex.com",
                "company_id": company["id"],
                "tags": ["vip"],
            },
            headers=admin_headers,
        )
    ).json()
    deal = (
        await client.post(
            "/api/v1/deals",
            json={
                "title": "Globex pilot",
                "contact_id": contact["id"],
                "company_id": company["id"],
            },
            headers=admin_headers,
        )
    ).json()
    task = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Call Sam", "contact_id": contact["id"], "due_date": "2020-01-01"},
            headers=admin_headers,
        )
    ).json()
    await client.post(
        "/api/v1/activities",
        json={"type": "call", "subject": "Intro call", "contact_id": contact["id"]},
        headers=admin_headers,
    )
    member_id = (await client.get("/api/v1/auth/me", headers=member_headers)).json()["id"]
    contact_id = contact["id"]
    ai.script = [
        calls(
            ("search_companies", {"query": "Glob"}),
            ("search_deals", {"query": "pilot"}),
            ("get_contact", {"contact_id": contact_id}),
            ("get_deal", {"deal_id": deal["id"]}),
            ("get_company", {"company_id": company["id"]}),
            ("list_tasks", {"overdue_only": True, "search": "Sam"}),
            ("list_pipeline_stages", {}),
            ("list_users", {}),
            ("get_dashboard_summary", {}),
            ("list_activities", {"contact_id": contact_id}),
            ("list_automations", {}),
            ("summarize_timeline", {"contact_id": contact_id}),
            ("draft_email", {"contact_id": contact_id, "purpose": "Check in"}),
        ),
        calls(
            ("update_task", {"task_id": task["id"], "due_date": "2030-01-01", "priority": "high"}),
            ("complete_task", {"task_id": task["id"]}),
            (
                "update_contact",
                {"contact_id": contact_id, "status": "prospect", "add_tags": ["hot", "vip"]},
            ),
            ("create_contact", {"first_name": "Lia", "email": "lia@globex.com"}),
            ("create_task", {"title": "Plan the week", "assignee_id": member_id}),
            ("create_company", {"name": "Initech", "industry": "Software"}),
            ("update_company", {"company_id": company["id"], "industry": "Energy"}),
            ("create_deal", {"title": "Initech deal", "value": 5000, "stage_name": "proposal"}),
            ("update_deal", {"deal_id": deal["id"], "value": 9000}),
            ("move_deal", {"deal_id": deal["id"], "stage_name": "Won"}),
            ("score_contact", {"contact_id": contact_id}),
            ("send_email", {"contact_id": contact_id, "subject": "Hi", "body": "Hello Sam"}),
        ),
        says("All done."),
    ]

    response = await client.post(URL, json=message("Do lots of things"), headers=admin_headers)

    assert response.status_code == 201, response.text
    reads = ai.tool_results(1)
    assert all("error" not in result for result in reads), reads
    assert reads[0]["companies"][0]["name"] == "Globex"
    assert reads[1]["deals"][0]["title"] == "Globex pilot"
    assert reads[2]["open_tasks"]["items"][0]["title"] == "Call Sam"
    assert reads[3]["deal"]["contact_id"] == contact_id
    assert reads[4]["contacts"]["items"][0]["name"] == "Sam"
    assert [t["title"] for t in reads[5]["tasks"]] == ["Call Sam"]
    assert reads[6]["stages"][0] == "Qualification"
    assert {u["name"] for u in reads[7]["users"]} == {"Ada Admin", "Max Member"}
    assert reads[8]["pipeline_by_stage"][0]["stage"] == "Qualification"
    assert reads[9]["activities"][0]["subject"] == "Intro call"
    assert reads[10] == {"webhook_subscriptions": []}
    assert reads[11]["summary"] == "Going well."
    assert reads[12] == {"subject": "Hi", "body": "Hello Sam", "sent": False}

    writes = ai.tool_results(2)
    assert all("error" not in result for result in writes), writes
    actions = response.json()["messages"][1]["actions"]
    assert [a["kind"] for a in actions] == [
        "updated",
        "completed",
        "updated",
        "created",
        "created",
        "created",
        "updated",
        "created",
        "updated",
        "moved",
        "scored",
        "sent",
    ]
    standalone = actions[4]
    assert standalone["label"] == "Task: Plan the week"
    assert standalone["link_entity"] is None  # no contact or deal to link to

    sam = (await client.get(f"/api/v1/contacts/{contact_id}", headers=admin_headers)).json()
    assert (sam["status"], sam["tags"], sam["ai_score"]) == ("prospect", ["vip", "hot"], 77)
    done = (await client.get(f"/api/v1/tasks/{task['id']}", headers=admin_headers)).json()
    assert (done["status"], done["priority"], done["due_date"]) == ("done", "high", "2030-01-01")
    won = (await client.get(f"/api/v1/deals/{deal['id']}", headers=admin_headers)).json()
    assert (won["stage"]["name"], won["value"]) == ("Won", 9000)
    globex = (await client.get(f"/api/v1/companies/{company['id']}", headers=admin_headers)).json()
    assert globex["industry"] == "Energy"
    planned = (
        await client.get("/api/v1/tasks", params={"search": "Plan"}, headers=admin_headers)
    ).json()
    assert planned["items"][0]["assignee"]["full_name"] == "Max Member"
    assert [m.to for m in mailer.outbox] == ["Sam <sam@globex.com>"]


async def test_members_cannot_see_automations(
    client: AsyncClient, member_headers: dict[str, str], ai: ScriptedAI
) -> None:
    ai.script = [calls(("list_automations", {})), says("Sorry.")]

    await client.post(URL, json=message("Show automations"), headers=member_headers)

    assert ai.tool_results()[0] == {"error": "Only admins can see automations"}


async def test_tool_problems_go_back_to_the_model(
    client: AsyncClient, admin_headers: dict[str, str], ai: ScriptedAI
) -> None:
    missing = "01a13653-9da7-73cb-8d45-ed41bb1c5691"
    ai.script = [
        calls(
            ("delete_everything", {}),
            ("create_task", {"title": ""}),
            ("get_contact", {"contact_id": missing}),
            ("move_deal", {"deal_id": missing, "stage_name": "Nope"}),
            ("create_contact", {"first_name": "Ok"}),
        ),
        says("Some of that failed."),
    ]

    response = await client.post(URL, json=message("Break things"), headers=admin_headers)

    assert response.status_code == 201
    errors = [result.get("error", "") for result in ai.tool_results()]
    assert "Unknown tool" in errors[0]
    assert "Invalid arguments" in errors[1]
    assert errors[2] == "Contact not found"
    assert errors[3].startswith("Unknown stage. Use one of: Qualification")
    assert errors[4] == ""  # the session still works after the failed calls
    assert [a["entity"] for a in response.json()["messages"][1]["actions"]] == ["contact"]
    # The conversation itself survived the rollbacks.
    assert response.json()["conversation"]["message_count"] == 2


async def test_gives_up_after_max_steps(
    client: AsyncClient, admin_headers: dict[str, str], ai: ScriptedAI
) -> None:
    # An empty script makes the fake keep calling tools forever.
    response = await client.post(URL, json=message("Loop"), headers=admin_headers)

    assert response.status_code == 201
    assert "more steps" in response.json()["messages"][1]["content"]
    assert len(ai.requests) == MAX_STEPS


async def test_smart_capture_from_a_file(
    client: AsyncClient, admin_headers: dict[str, str], ai: ScriptedAI
) -> None:
    response = await client.post(
        "/api/v1/ai/extract-contact/file",
        files={"file": ("signature.txt", b"Dana Lee\nAcme", "text/plain")},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["first_name"] == "Dana"
    assert response.json()["source_text"] == "Dana Lee\nAcme"

    unsupported = await client.post(
        "/api/v1/ai/extract-contact/file",
        files={"file": ("a.zip", b"PK", "application/zip")},
        headers=admin_headers,
    )
    assert unsupported.status_code == 400


async def test_task_questions_see_the_whole_team_like_the_dashboard(
    client: AsyncClient,
    admin_headers: dict[str, str],
    member_headers: dict[str, str],
    ai: ScriptedAI,
) -> None:
    member_id = (await client.get("/api/v1/auth/me", headers=member_headers)).json()["id"]
    for title in ("Late one", "Late two"):
        await client.post(
            "/api/v1/tasks",
            json={"title": title, "due_date": "2020-01-01", "assignee_id": member_id},
            headers=admin_headers,
        )
    done = (
        await client.post(
            "/api/v1/tasks",
            json={"title": "Finished", "status": "done", "assignee_id": member_id},
            headers=admin_headers,
        )
    ).json()
    ai.script = [
        calls(
            ("list_tasks", {"overdue_only": True}),
            ("list_tasks", {"assignee": "me"}),
            ("list_tasks", {"assignee": member_id, "include_done": True}),
            ("list_tasks", {"assignee": "nobody"}),
            ("get_dashboard_summary", {}),
        ),
        says("Two overdue tasks."),
    ]

    response = await client.post(URL, json=message("Any overdue tasks?"), headers=admin_headers)

    assert response.status_code == 201, response.text
    team, mine, member, unknown, dashboard = ai.tool_results(1)
    assert team["total"] == 2
    assert {t["title"] for t in team["tasks"]} == {"Late one", "Late two"}
    assert mine == {"assignee": "me", "total": 0, "tasks": []}
    assert done["title"] in {t["title"] for t in member["tasks"]}
    assert member["total"] == 3
    assert "error" in unknown
    assert dashboard["overdue_tasks_all_users"] == 2
    assert len(dashboard["overdue_task_list"]) == 2
