"""Small JSON views and pagination metadata returned by assistant tools."""

import uuid
from collections.abc import Callable
from typing import Any

from app.modules.activities.models import Activity
from app.modules.activities.schemas import ActivityRead
from app.modules.assistant.tools.definitions import RESULT_LIMIT
from app.modules.companies.models import Company
from app.modules.companies.schemas import CompanyRead
from app.modules.contacts.models import Contact
from app.modules.contacts.schemas import ContactRead
from app.modules.deals.models import Deal
from app.modules.deals.schemas import DealRead
from app.modules.tasks.models import Task
from app.modules.tasks.schemas import TaskRead
from app.shared.pagination import Page, PageParams
from app.shared.schemas import ContactRef


def _name(contact: Contact | ContactRead | ContactRef) -> str:
    return f"{contact.first_name} {contact.last_name or ''}".strip()


def _contact_view(contact: Contact | ContactRead) -> dict[str, Any]:
    return {
        "id": str(contact.id),
        "name": _name(contact),
        "email": contact.email,
        "phone": contact.phone,
        "job_title": contact.job_title,
        "status": contact.status,
        "company": contact.company.name if contact.company else None,
        "owner": contact.owner.full_name if contact.owner else None,
        "tags": contact.tags,
        "ai_score": contact.ai_score,
    }


def _company_view(company: Company | CompanyRead) -> dict[str, Any]:
    return {
        "id": str(company.id),
        "name": company.name,
        "industry": company.industry,
        "domain": company.domain,
    }


def _deal_view(deal: Deal | DealRead) -> dict[str, Any]:
    return {
        "id": str(deal.id),
        "title": deal.title,
        "value": float(deal.value),
        "currency": deal.currency,
        "stage": deal.stage.name,
        "contact": _name(deal.contact) if deal.contact else None,
        "company": deal.company.name if deal.company else None,
        "expected_close_date": deal.expected_close_date,
    }


def _task_view(task: Task | TaskRead) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "title": task.title,
        "due_date": task.due_date,
        "priority": task.priority,
        "status": task.status,
        "assignee": task.assignee.full_name if task.assignee else None,
        "contact": _name(task.contact) if task.contact else None,
        "deal": task.deal.title if task.deal else None,
    }


def _activity_view(activity: Activity | ActivityRead) -> dict[str, Any]:
    return {
        "type": activity.type,
        "subject": activity.subject,
        "body": (activity.body or "")[:300],
        "occurred_at": activity.occurred_at,
    }


def _page(size: int = RESULT_LIMIT) -> PageParams:
    return PageParams(page=1, size=size)


def _listing[T](key: str, page: Page[T], view: Callable[[T], dict[str, Any]]) -> dict[str, Any]:
    """A list result with its real total, so the model never mistakes a partial list for all."""
    result = {"total": page.total, key: [view(item) for item in page.items]}
    if page.total > len(page.items):
        result["note"] = f"Showing {len(page.items)} of {page.total}; narrow the filters for more."
    return result


def _link_for(contact_id: uuid.UUID | None, deal_id: uuid.UUID | None) -> dict[str, Any]:
    """Tasks and activities have no page of their own: link to their contact or deal."""
    if contact_id:
        return {"link_entity": "contact", "link_id": contact_id}
    if deal_id:
        return {"link_entity": "deal", "link_id": deal_id}
    return {}
