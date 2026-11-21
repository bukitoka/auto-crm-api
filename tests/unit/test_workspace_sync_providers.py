from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.modules.workspace_sync import providers


@pytest.mark.parametrize("name", ["google", "microsoft"])
async def test_calendar_and_inbox_provider_mapping(name, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 11, 21, 9, tzinfo=UTC)
    monkeypatch.setattr(providers, "utc_now", lambda: now)

    google_calendar = {
        "items": [
            {
                "id": "meeting",
                "summary": "Review",
                "start": {"dateTime": "2026-11-22T08:00:00+08:00"},
                "end": {"dateTime": "2026-11-22T09:00:00+08:00"},
                "attendees": [{"email": "jane@example.com"}],
            },
            {"id": "holiday", "start": {"date": "2026-11-23"}},
        ]
    }
    ms_calendar = {
        "value": [
            {
                "id": "meeting",
                "subject": "Review",
                "start": {"dateTime": "2026-11-22T00:00:00.0000000"},
                "end": {"dateTime": "2026-11-22T01:00:00.0000000"},
                "attendees": [{"emailAddress": {"address": "jane@example.com"}}],
            },
            {"id": "holiday", "isAllDay": True},
        ]
    }
    responses: dict[str, dict[str, Any]] = {
        "/gmail/v1/users/me/profile": {"emailAddress": "account"},
        "/calendar/v3/calendars/primary/events": google_calendar,
        "/gmail/v1/users/me/messages": {"messages": [{"id": "reply"}]},
        "/gmail/v1/users/me/messages/reply": {
            "id": "reply",
            "internalDate": str(int(now.timestamp() * 1000)),
            "payload": {
                "headers": [
                    {"name": "From", "value": "Jane <jane@example.com>"},
                    {"name": "Subject", "value": "Re: Review"},
                ]
            },
        },
        "/v1.0/me": {"id": "account"},
        "/v1.0/me/calendarView": ms_calendar,
        "/v1.0/me/mailFolders/inbox/messages": {
            "value": [
                {
                    "id": "reply",
                    "receivedDateTime": now.isoformat(),
                    "subject": "Re: Review",
                    "from": {"emailAddress": {"address": "jane@example.com"}},
                }
            ]
        },
    }

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/gmail/v1/users/me/messages":
            assert "q" not in request.url.params
        if request.url.path.endswith("/messages/reply"):
            assert request.url.params["format"] == "metadata"
        return httpx.Response(200, json=responses[request.url.path])

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        account, events, mail = await providers.fetch_account(client, name)
    assert account == "account"
    assert [(event.title, event.attendees) for event in events] == [
        ("Review", ("jane@example.com",))
    ]
    assert events[0].starts == datetime(2026, 11, 22, 0, tzinfo=UTC)
    assert [(message.sender, message.subject) for message in mail] == [
        ("jane@example.com", "Re: Review")
    ]
