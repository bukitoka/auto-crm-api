import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
from typing import Any, Literal
from urllib.parse import quote, urlencode

import httpx

from app.core.config import settings
from app.core.exceptions import ServiceUnavailableError
from app.shared.utils import utc_now

ProviderName = Literal["google", "microsoft"]
GOOGLE = "https://www.googleapis.com"
GRAPH = "https://graph.microsoft.com/v1.0"


@dataclass(frozen=True)
class ExternalEvent:
    id: str
    title: str
    starts: datetime
    ends: datetime
    attendees: tuple[str, ...]


@dataclass(frozen=True)
class ExternalMail:
    id: str
    sender: str
    subject: str
    received: datetime


@dataclass(frozen=True)
class Provider:
    authorize: str
    token: str
    scopes: str
    client_id: str
    client_secret: str

    def authorization_url(self, state: str, challenge: str) -> str:
        return f"{self.authorize}?" + urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": callback_url(),
                "response_type": "code",
                "scope": self.scopes,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )

    async def exchange(self, client: httpx.AsyncClient, code: str, verifier: str) -> str:
        response = await client.post(
            self.token,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": callback_url(),
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("Provider did not return an access token")
        return token


def callback_url() -> str:
    return f"{settings.frontend_url.rstrip('/')}/settings/sync/callback"


def enabled_providers() -> list[ProviderName]:
    enabled: list[ProviderName] = []
    if settings.google_sync_client_id and settings.google_sync_client_secret:
        enabled.append("google")
    if settings.microsoft_sync_client_id and settings.microsoft_sync_client_secret:
        enabled.append("microsoft")
    return enabled


def provider(name: ProviderName) -> Provider:
    if name not in enabled_providers():
        raise ServiceUnavailableError("This sync provider is not configured")
    if name == "google":
        return Provider(
            "https://accounts.google.com/o/oauth2/v2/auth",
            "https://oauth2.googleapis.com/token",
            "https://www.googleapis.com/auth/calendar.events.readonly "
            "https://www.googleapis.com/auth/gmail.metadata",
            settings.google_sync_client_id,
            settings.google_sync_client_secret,
        )
    return Provider(
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "User.Read Calendars.Read Mail.ReadBasic",
        settings.microsoft_sync_client_id,
        settings.microsoft_sync_client_secret,
    )


async def get_json(client: httpx.AsyncClient, url: str, **kwargs: Any) -> dict[str, Any]:
    response = await client.get(url, **kwargs)
    response.raise_for_status()
    return response.json()


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


async def _google_data(
    client: httpx.AsyncClient,
) -> tuple[str, list[ExternalEvent], list[ExternalMail]]:
    now = utc_now()
    profile, calendar, inbox = await asyncio.gather(
        get_json(client, f"{GOOGLE}/gmail/v1/users/me/profile"),
        get_json(
            client,
            f"{GOOGLE}/calendar/v3/calendars/primary/events",
            params={
                "timeMin": now.isoformat(),
                "timeMax": (now + timedelta(days=31)).isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 100,
            },
        ),
        get_json(
            client,
            f"{GOOGLE}/gmail/v1/users/me/messages",
            params={
                "labelIds": "INBOX",
                "maxResults": 25,
            },
        ),
    )
    events = [
        ExternalEvent(
            item["id"],
            item.get("summary") or "Calendar event",
            _datetime(item["start"]["dateTime"]),
            _datetime(item["end"]["dateTime"]),
            tuple(person["email"] for person in item.get("attendees", []) if person.get("email")),
        )
        for item in calendar.get("items", [])
        if item.get("status") != "cancelled"
        and item.get("start", {}).get("dateTime")
        and item.get("end", {}).get("dateTime")
    ]
    details = await asyncio.gather(
        *[
            get_json(
                client,
                f"{GOOGLE}/gmail/v1/users/me/messages/{quote(item['id'], safe='')}",
                params=[
                    ("format", "metadata"),
                    ("metadataHeaders", "From"),
                    ("metadataHeaders", "Subject"),
                ],
            )
            for item in inbox.get("messages", [])
        ]
    )
    mail = []
    for item in details:
        headers = {
            header["name"].lower(): header["value"]
            for header in item.get("payload", {}).get("headers", [])
        }
        mail.append(
            ExternalMail(
                item["id"],
                parseaddr(headers.get("from", ""))[1],
                headers.get("subject", ""),
                datetime.fromtimestamp(int(item["internalDate"]) / 1000, UTC),
            )
        )
    return (
        profile["emailAddress"],
        events,
        [item for item in mail if item.received >= now - timedelta(days=30)],
    )


async def _microsoft_data(
    client: httpx.AsyncClient,
) -> tuple[str, list[ExternalEvent], list[ExternalMail]]:
    now = utc_now()
    profile, calendar, inbox = await asyncio.gather(
        get_json(client, f"{GRAPH}/me", params={"$select": "id"}),
        get_json(
            client,
            f"{GRAPH}/me/calendarView",
            params={
                "startDateTime": now.isoformat(),
                "endDateTime": (now + timedelta(days=31)).isoformat(),
                "$top": 100,
                "$select": "id,subject,start,end,attendees,isAllDay,isCancelled",
            },
            headers={"Prefer": 'outlook.timezone="UTC", IdType="ImmutableId"'},
        ),
        get_json(
            client,
            f"{GRAPH}/me/mailFolders/inbox/messages",
            params={
                "$top": 25,
                "$orderby": "receivedDateTime desc",
                "$filter": f"receivedDateTime ge {(now - timedelta(days=30)).isoformat()}",
                "$select": "id,subject,from,receivedDateTime",
            },
            headers={"Prefer": 'IdType="ImmutableId"'},
        ),
    )
    events = [
        ExternalEvent(
            item["id"],
            item.get("subject") or "Calendar event",
            _datetime(item["start"]["dateTime"]),
            _datetime(item["end"]["dateTime"]),
            tuple(person["emailAddress"]["address"] for person in item.get("attendees", [])),
        )
        for item in calendar.get("value", [])
        if not item.get("isAllDay") and not item.get("isCancelled")
    ]
    mail = [
        ExternalMail(
            item["id"],
            item.get("from", {}).get("emailAddress", {}).get("address", ""),
            item.get("subject") or "",
            _datetime(item["receivedDateTime"]),
        )
        for item in inbox.get("value", [])
    ]
    return profile["id"], events, mail


async def fetch_account(
    client: httpx.AsyncClient, name: ProviderName
) -> tuple[str, list[ExternalEvent], list[ExternalMail]]:
    if name == "google":
        return await _google_data(client)
    return await _microsoft_data(client)
