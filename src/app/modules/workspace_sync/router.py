import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

import httpx
import jwt
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionDep
from app.core.exceptions import BadRequestError
from app.modules.activities.models import Activity, ActivityType
from app.modules.auth.dependencies import WorkingUser
from app.modules.calendar.models import CalendarEvent
from app.modules.contacts.models import Contact
from app.modules.users.models import User
from app.modules.workspace_sync.models import SyncImport
from app.modules.workspace_sync.providers import (
    ExternalEvent,
    ExternalMail,
    ProviderName,
    enabled_providers,
    fetch_account,
    provider,
)
from app.shared.utils import utc_now

router = APIRouter(prefix="/workspace-sync", tags=["workspace sync"])


def _base64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _verifier(state: str) -> str:
    return _base64(
        hmac.digest(settings.jwt_secret_key.encode(), f"sync-pkce:{state}".encode(), "sha256")
    )


class SyncCallback(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=2048)


class SyncResult(BaseModel):
    events_added: int = 0
    events_updated: int = 0
    emails_logged: int = 0


@router.get("/providers", response_model=list[ProviderName])
async def providers_list(_: WorkingUser):
    return enabled_providers()


@router.post("/{name}/start")
async def start_sync(name: ProviderName, user: WorkingUser) -> dict[str, str]:
    config = provider(name)
    state = jwt.encode(
        {
            "sub": str(user.id),
            "purpose": "workspace-sync",
            "provider": name,
            "nonce": secrets.token_urlsafe(16),
            "exp": utc_now() + timedelta(minutes=10),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {
        "url": config.authorization_url(
            state, _base64(hashlib.sha256(_verifier(state).encode()).digest())
        )
    }


@router.post("/{name}/complete", response_model=SyncResult)
async def complete_sync(
    name: ProviderName, data: SyncCallback, user: WorkingUser, session: SessionDep
):
    try:
        state = jwt.decode(data.state, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise BadRequestError("This sync session expired. Start again from Settings.") from exc
    if (state.get("purpose"), state.get("provider"), state.get("sub")) != (
        "workspace-sync",
        name,
        str(user.id),
    ):
        raise BadRequestError("Invalid sync session")
    config = provider(name)
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            token = await config.exchange(client, data.code, _verifier(data.state))
            client.headers["Authorization"] = f"Bearer {token}"
            account, events, mail = await fetch_account(client, name)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise BadRequestError(
            "Could not read your provider account. Try connecting again."
        ) from exc
    return await import_account(session, user, name, account, events, mail)


async def import_account(
    session: AsyncSession,
    user: User,
    name: ProviderName,
    account: str,
    events: list[ExternalEvent],
    mail: list[ExternalMail],
) -> SyncResult:
    prefix = f"{user.id}:{name}:{account}"
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(prefix))))
    result = SyncResult()
    addresses = {
        address.lower()
        for address in [
            *(email.sender for email in mail),
            *(email for event in events for email in event.attendees),
        ]
        if address
    }
    contacts = dict(
        (
            await session.execute(
                select(func.lower(Contact.email), Contact.id).where(
                    Contact.owner_id == user.id, func.lower(Contact.email).in_(addresses)
                )
            )
        ).all()
    )
    sources = {
        (kind, obj.id): hashlib.sha256(f"{prefix}:{kind}:{obj.id}".encode()).hexdigest()
        for kind, items in (("event", events), ("mail", mail))
        for obj in items
    }
    rows = await session.scalars(
        select(SyncImport).where(
            SyncImport.owner_id == user.id, SyncImport.source_key.in_(sources.values())
        )
    )
    imported = {item.source_key: item for item in rows}
    now = utc_now()
    for event in events:
        if event.starts < now or event.ends <= event.starts:
            continue
        key = sources["event", event.id]
        previous = imported.get(key)
        if previous:
            stored = (
                await session.get(CalendarEvent, previous.event_id) if previous.event_id else None
            )
            if stored and (stored.title, stored.starts_at, stored.ends_at) != (
                event.title[:200],
                event.starts,
                event.ends,
            ):
                stored.title, stored.starts_at, stored.ends_at = (
                    event.title[:200],
                    event.starts,
                    event.ends,
                )
                result.events_updated += 1
            continue
        contact_id = next(
            (contacts[email.lower()] for email in event.attendees if email.lower() in contacts),
            None,
        )
        stored = CalendarEvent(
            owner_id=user.id,
            contact_id=contact_id,
            title=event.title[:200],
            starts_at=event.starts,
            ends_at=event.ends,
        )
        session.add(stored)
        await session.flush()
        item = SyncImport(owner_id=user.id, source_key=key, event_id=stored.id)
        session.add(item)
        imported[key] = item
        result.events_added += 1
    for email in mail:
        key = sources["mail", email.id]
        contact_id = contacts.get(email.sender.lower())
        if key in imported or contact_id is None:
            continue
        session.add(
            Activity(
                type=ActivityType.EMAIL,
                subject=(email.subject or "Email received")[:200],
                occurred_at=email.received,
                contact_id=contact_id,
                created_by_id=user.id,
            )
        )
        item = SyncImport(owner_id=user.id, source_key=key)
        session.add(item)
        imported[key] = item
        result.emails_logged += 1
    await session.commit()
    return result
