"""Per-request data scope, enforced on the SQLAlchemy session.

Every route, service, AI tool and dashboard query reads through the same session, so
scoping it once covers all of them:

- An admin gets `owner_id=<their id>`: queries only return their own records and writes
  of anyone else's records are refused.
- The super admin gets `read_only=True`: queries see everything, CRM writes are refused.
- No scope (the automation service account, scripts, tests) means unrestricted.
"""

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.core.exceptions import PermissionDeniedError

SCOPE_KEY = "scope"
# Set on a statement that must see every owner, e.g. the global contact email check.
SKIP_SCOPE = "skip_owner_scope"


@dataclass(frozen=True, slots=True)
class Scope:
    owner_id: uuid.UUID | None = None
    read_only: bool = False


def set_scope(session: AsyncSession, scope: Scope | None) -> None:
    if scope is None:
        session.sync_session.info.pop(SCOPE_KEY, None)
    else:
        session.sync_session.info[SCOPE_KEY] = scope


def scope_for(user: Any) -> Scope:
    """The super admin sees everything read-only; an admin sees only their own records."""
    return Scope(read_only=True) if user.is_super_admin else Scope(owner_id=user.id)


def get_scope(session: AsyncSession | Session) -> Scope | None:
    target = session.sync_session if isinstance(session, AsyncSession) else session
    return target.info.get(SCOPE_KEY)


@contextmanager
def unscoped(session: AsyncSession) -> Generator[None]:
    """Suspend the scope for a system action the caller has already authorised."""
    previous = get_scope(session)
    set_scope(session, None)
    try:
        yield
    finally:
        set_scope(session, previous)


def ensure_own(session: AsyncSession, owner_id: uuid.UUID | None) -> None:
    """Refuse handing a record to someone else when the session is scoped to one admin."""
    scope = get_scope(session)
    if scope and scope.owner_id and owner_id not in (None, scope.owner_id):
        raise PermissionDeniedError("You can only assign records to yourself")


def _crm_models() -> dict[str, Any]:
    # Imported lazily: the models import `app.shared.models`, which would cycle at load time.
    from app.modules.activities.models import Activity
    from app.modules.companies.models import Company
    from app.modules.contacts.models import Contact
    from app.modules.deals.models import Deal
    from app.modules.tasks.models import Task

    return {
        "contact": Contact,
        "company": Company,
        "deal": Deal,
        "task": Task,
        "activity": Activity,
    }


@event.listens_for(Session, "do_orm_execute")
def _apply_scope(state: ORMExecuteState) -> None:
    scope: Scope | None = state.session.info.get(SCOPE_KEY)
    if (
        scope is None
        or scope.owner_id is None
        or not state.is_select
        or state.execution_options.get(SKIP_SCOPE)
    ):
        return
    owner = scope.owner_id
    m = _crm_models()
    contact, company, deal, task, activity = (
        m["contact"],
        m["company"],
        m["deal"],
        m["task"],
        m["activity"],
    )
    state.statement = state.statement.options(
        with_loader_criteria(contact, lambda cls: cls.owner_id == owner, include_aliases=True),
        with_loader_criteria(company, lambda cls: cls.owner_id == owner, include_aliases=True),
        with_loader_criteria(deal, lambda cls: cls.owner_id == owner, include_aliases=True),
        with_loader_criteria(task, lambda cls: cls.assignee_id == owner, include_aliases=True),
        with_loader_criteria(
            activity,
            lambda cls: or_(
                cls.created_by_id == owner,
                cls.contact_id.in_(select(contact.id).where(contact.owner_id == owner)),
                cls.deal_id.in_(select(deal.id).where(deal.owner_id == owner)),
            ),
            include_aliases=True,
        ),
    )


@event.listens_for(Session, "before_flush")
def _guard_writes(session: Session, flush_context: Any, instances: Any) -> None:
    scope: Scope | None = session.info.get(SCOPE_KEY)
    if scope is None:
        return
    crm = _crm_models()
    activity = crm.pop("activity")
    models = (*crm.values(), activity)
    changed = [
        obj for obj in (*session.new, *session.dirty, *session.deleted) if isinstance(obj, models)
    ]
    if scope.read_only and changed:
        raise PermissionDeniedError("The super admin can view data but not change it")
    if scope.owner_id is None:
        return
    for obj in changed:
        # Activities belong to whoever owns the contact or deal; the service checks that link.
        if isinstance(obj, activity) or obj in session.deleted:
            continue
        owner = obj.assignee_id if hasattr(obj, "assignee_id") else obj.owner_id
        if owner != scope.owner_id:
            raise PermissionDeniedError("You can only work with your own records")
