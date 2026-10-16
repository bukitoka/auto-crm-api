"""Tools the assistant can call. Each tool is a Pydantic model of its arguments plus a handler.

The model's JSON arguments are validated with the Pydantic model, and the handler uses the
regular services, so the assistant follows exactly the same rules (and fires the same
webhook events) as the web app. Handlers return small JSON-friendly dicts for the model.

To add a tool: write a params model, an async handler, and add a `Tool(...)` to `TOOLS`.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import Mailer
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.modules.activities.models import Activity, ActivityType
from app.modules.activities.schemas import ActivityCreate, ActivityFilters, ActivityRead
from app.modules.activities.service import ActivityService
from app.modules.ai.client import AIClient
from app.modules.ai.schemas import EmailDraftRequest, SummarizeRequest
from app.modules.ai.service import AIService
from app.modules.assistant.schemas import AssistantAction
from app.modules.companies.models import Company
from app.modules.companies.schemas import (
    CompanyCreate,
    CompanyFilters,
    CompanyRead,
    CompanyUpdate,
)
from app.modules.companies.service import CompanyService
from app.modules.contacts.models import Contact, ContactStatus
from app.modules.contacts.schemas import ContactCreate, ContactFilters, ContactRead, ContactUpdate
from app.modules.contacts.service import ContactService
from app.modules.dashboard.service import DashboardService
from app.modules.deals.models import Deal
from app.modules.deals.schemas import DealCreate, DealFilters, DealRead, DealUpdate
from app.modules.deals.service import DealService
from app.modules.emails.schemas import EmailSendRequest
from app.modules.emails.service import EmailService
from app.modules.pipeline.repository import PipelineRepository
from app.modules.tasks.models import Task, TaskPriority, TaskStatus
from app.modules.tasks.schemas import TaskCreate, TaskFilters, TaskRead, TaskUpdate
from app.modules.tasks.service import TaskService
from app.modules.users.models import User, UserRole
from app.modules.users.service import SERVICE_ACCOUNT_EMAIL, UserService
from app.modules.webhooks.service import WebhookService
from app.shared.pagination import PageParams

RESULT_LIMIT = 25


@dataclass
class ToolContext:
    """What every handler gets: services bound to this request, the user, and an action log."""

    session: AsyncSession
    user: User
    ai: AIClient
    mailer: Mailer
    actions: list[AssistantAction] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.contacts = ContactService(self.session)
        self.companies = CompanyService(self.session)
        self.deals = DealService(self.session)
        self.tasks = TaskService(self.session)
        self.activities = ActivityService(self.session)
        self.pipeline = PipelineRepository(self.session)
        self.users = UserService(self.session)
        self.dashboard = DashboardService(self.session)
        self.ai_features = AIService(self.session, self.ai)
        self.emails = EmailService(self.session, self.mailer)
        self.webhooks = WebhookService(self.session)


Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: type[BaseModel]
    handler: Handler

    def spec(self) -> dict[str, Any]:
        """The OpenAI/DeepSeek function-calling definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.params.model_json_schema(),
            },
        }


# --- Compact views for the model (only what it needs to answer and to call other tools) ---
# They accept ORM objects (from `service.get/create`) and schemas (from `service.list_page`).


def _name(contact: Contact | ContactRead | Any) -> str:
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


def _listing(key: str, page: Any, view: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
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


# --- Read tools ---


class SearchContactsParams(BaseModel):
    query: str | None = Field(default=None, description="Name, email or phone; omit to list all")
    status: ContactStatus | None = None
    company_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = Field(default=None, description="A teammate from list_users")


async def search_contacts(ctx: ToolContext, params: SearchContactsParams) -> dict[str, Any]:
    filters = ContactFilters(search=params.query, **params.model_dump(exclude={"query"}))
    page = await ctx.contacts.list_page(filters, _page())
    return _listing("contacts", page, _contact_view)


class SearchCompaniesParams(BaseModel):
    query: str | None = Field(default=None, description="Company name; omit to list all")
    industry: str | None = None


async def search_companies(ctx: ToolContext, params: SearchCompaniesParams) -> dict[str, Any]:
    filters = CompanyFilters(search=params.query, industry=params.industry)
    page = await ctx.companies.list_page(filters, _page())
    return _listing("companies", page, _company_view)


class SearchDealsParams(BaseModel):
    query: str | None = Field(default=None, description="Words in the title; omit to list all")
    stage_name: str | None = Field(default=None, description="Only deals in this stage")
    contact_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = Field(default=None, description="A teammate from list_users")


async def search_deals(ctx: ToolContext, params: SearchDealsParams) -> dict[str, Any]:
    filters = DealFilters(
        search=params.query,
        stage_id=await _stage_id(ctx, params.stage_name) if params.stage_name else None,
        **params.model_dump(exclude={"query", "stage_name"}),
    )
    page = await ctx.deals.list_page(filters, _page())
    return _listing("deals", page, _deal_view)


class ContactIdParams(BaseModel):
    contact_id: uuid.UUID


async def get_contact(ctx: ToolContext, params: ContactIdParams) -> dict[str, Any]:
    contact = await ctx.contacts.get(params.contact_id)
    deals = await ctx.deals.list_page(DealFilters(contact_id=contact.id), _page())
    tasks = await ctx.tasks.list_page(TaskFilters(contact_id=contact.id, open=True), _page())
    activities = await ctx.activities.list_page(ActivityFilters(contact_id=contact.id), _page(5))
    return {
        "contact": _contact_view(contact) | {"ai_summary": contact.ai_summary},
        "deals": _listing("items", deals, _deal_view),
        "open_tasks": _listing("items", tasks, _task_view),
        "recent_activities": _listing("items", activities, _activity_view),
    }


class DealIdParams(BaseModel):
    deal_id: uuid.UUID


async def get_deal(ctx: ToolContext, params: DealIdParams) -> dict[str, Any]:
    deal = await ctx.deals.get(params.deal_id)
    tasks = await ctx.tasks.list_page(TaskFilters(deal_id=deal.id, open=True), _page())
    activities = await ctx.activities.list_page(ActivityFilters(deal_id=deal.id), _page(5))
    return {
        "deal": _deal_view(deal) | {"contact_id": deal.contact_id, "company_id": deal.company_id},
        "open_tasks": _listing("items", tasks, _task_view),
        "recent_activities": _listing("items", activities, _activity_view),
    }


class CompanyIdParams(BaseModel):
    company_id: uuid.UUID


async def get_company(ctx: ToolContext, params: CompanyIdParams) -> dict[str, Any]:
    company = await ctx.companies.get(params.company_id)
    contacts = await ctx.contacts.list_page(ContactFilters(company_id=company.id), _page())
    deals = await ctx.deals.list_page(DealFilters(company_id=company.id), _page())
    return {
        "company": _company_view(company) | {"website": company.website, "notes": company.notes},
        "contacts": _listing("items", contacts, _contact_view),
        "deals": _listing("items", deals, _deal_view),
    }


class ListTasksParams(BaseModel):
    search: str | None = Field(default=None, description="Words in the task title")
    assignee: str = Field(
        default="all",
        description='"all" (whole team, like the dashboard), "me" (the current user) '
        "or a teammate's user id from list_users",
    )
    overdue_only: bool = False
    include_done: bool = False
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None


async def list_tasks(ctx: ToolContext, params: ListTasksParams) -> dict[str, Any]:
    scope = params.assignee.strip().lower()
    if scope == "all":
        assignee_id = None
    elif scope == "me":
        assignee_id = ctx.user.id
    else:
        try:
            assignee_id = uuid.UUID(scope)
        except ValueError:
            raise NotFoundError('Unknown assignee. Use "all", "me" or a user id') from None
    filters = TaskFilters(
        search=params.search,
        assignee_id=assignee_id,
        overdue=True if params.overdue_only else None,
        open=None if params.include_done else True,
        contact_id=params.contact_id,
        deal_id=params.deal_id,
    )
    page = await ctx.tasks.list_page(filters, _page())
    return {"assignee": scope} | _listing("tasks", page, _task_view)


class NoParams(BaseModel):
    pass


async def list_pipeline_stages(ctx: ToolContext, _: NoParams) -> dict[str, Any]:
    stages = await ctx.pipeline.list_stages()
    return {"stages": [s.name for s in stages]}


# --- Write tools ---


class CreateTaskParams(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    due_date: date | None = Field(default=None, description="YYYY-MM-DD")
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_id: uuid.UUID | None = Field(
        default=None, description="A teammate from list_users; defaults to the current user"
    )
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None


async def create_task(ctx: ToolContext, params: CreateTaskParams) -> dict[str, Any]:
    task = await ctx.tasks.create(TaskCreate(**params.model_dump()), user=ctx.user)
    due = f" (due {task.due_date:%b %-d})" if task.due_date else ""
    ctx.actions.append(
        AssistantAction(
            kind="created",
            entity="task",
            entity_id=task.id,
            label=f"Task: {task.title}{due}",
            **_link_for(task.contact_id, task.deal_id),
        )
    )
    return {"created_task": _task_view(task)}


class TaskIdParams(BaseModel):
    task_id: uuid.UUID


async def complete_task(ctx: ToolContext, params: TaskIdParams) -> dict[str, Any]:
    task = await ctx.tasks.update(params.task_id, TaskUpdate(status=TaskStatus.DONE))
    ctx.actions.append(
        AssistantAction(
            kind="completed",
            entity="task",
            entity_id=task.id,
            label=f"Completed: {task.title}",
            **_link_for(task.contact_id, task.deal_id),
        )
    )
    return {"completed_task": _task_view(task)}


class UpdateTaskParams(BaseModel):
    task_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=200)
    due_date: date | None = Field(default=None, description="New due date, YYYY-MM-DD")
    priority: TaskPriority | None = None
    description: str | None = None
    assignee_id: uuid.UUID | None = None


async def update_task(ctx: ToolContext, params: UpdateTaskParams) -> dict[str, Any]:
    changes = params.model_dump(exclude={"task_id"}, exclude_none=True)
    task = await ctx.tasks.update(params.task_id, TaskUpdate(**changes))
    ctx.actions.append(
        AssistantAction(
            kind="updated",
            entity="task",
            entity_id=task.id,
            label=f"Updated task: {task.title}",
            **_link_for(task.contact_id, task.deal_id),
        )
    )
    return {"updated_task": _task_view(task)}


class LogActivityParams(BaseModel):
    type: ActivityType = Field(description="note, call, email or meeting")
    subject: str = Field(min_length=1, max_length=200)
    body: str | None = None
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None


async def log_activity(ctx: ToolContext, params: LogActivityParams) -> dict[str, Any]:
    activity = await ctx.activities.create(ActivityCreate(**params.model_dump()), user=ctx.user)
    ctx.actions.append(
        AssistantAction(
            kind="logged",
            entity="activity",
            entity_id=activity.id,
            label=f"{activity.type.capitalize()}: {activity.subject}",
            **_link_for(activity.contact_id, activity.deal_id),
        )
    )
    return {"logged_activity": _activity_view(activity)}


class CreateContactParams(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    job_title: str | None = None
    status: ContactStatus = ContactStatus.LEAD
    company_id: uuid.UUID | None = None


async def create_contact(ctx: ToolContext, params: CreateContactParams) -> dict[str, Any]:
    contact = await ctx.contacts.create(ContactCreate(**params.model_dump()), user=ctx.user)
    ctx.actions.append(
        AssistantAction(
            kind="created",
            entity="contact",
            entity_id=contact.id,
            label=f"Contact: {_name(contact)}",
        )
    )
    return {"created_contact": _contact_view(contact)}


class UpdateContactParams(BaseModel):
    contact_id: uuid.UUID
    status: ContactStatus | None = None
    job_title: str | None = None
    email: str | None = None
    phone: str | None = None
    company_id: uuid.UUID | None = None
    add_tags: list[str] = Field(default_factory=list, description="Tags to add")


async def update_contact(ctx: ToolContext, params: UpdateContactParams) -> dict[str, Any]:
    contact = await ctx.contacts.get(params.contact_id)
    changes = params.model_dump(exclude={"contact_id", "add_tags"}, exclude_none=True)
    if params.add_tags:
        changes["tags"] = list(dict.fromkeys([*contact.tags, *params.add_tags]))
    contact = await ctx.contacts.update(contact.id, ContactUpdate(**changes))
    ctx.actions.append(
        AssistantAction(
            kind="updated",
            entity="contact",
            entity_id=contact.id,
            label=f"Updated {_name(contact)}",
        )
    )
    return {"updated_contact": _contact_view(contact)}


class CreateCompanyParams(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    domain: str | None = None
    industry: str | None = None
    website: str | None = None


async def create_company(ctx: ToolContext, params: CreateCompanyParams) -> dict[str, Any]:
    company = await ctx.companies.create(CompanyCreate(**params.model_dump()), user=ctx.user)
    ctx.actions.append(
        AssistantAction(
            kind="created", entity="company", entity_id=company.id, label=f"Company: {company.name}"
        )
    )
    return {"created_company": _company_view(company)}


async def _stage_id(ctx: ToolContext, name: str) -> uuid.UUID:
    stages = await ctx.pipeline.list_stages()
    for stage in stages:
        if stage.name.lower() == name.strip().lower():
            return stage.id
    raise NotFoundError(f"Unknown stage. Use one of: {', '.join(s.name for s in stages)}")


class CreateDealParams(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    value: Decimal = Field(default=Decimal(0), ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    stage_name: str | None = Field(default=None, description="Defaults to the first stage")
    contact_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    expected_close_date: date | None = None


async def create_deal(ctx: ToolContext, params: CreateDealParams) -> dict[str, Any]:
    values = params.model_dump(exclude={"stage_name"})
    if params.stage_name:
        values["stage_id"] = await _stage_id(ctx, params.stage_name)
    deal = await ctx.deals.create(DealCreate(**values), user=ctx.user)
    ctx.actions.append(
        AssistantAction(
            kind="created", entity="deal", entity_id=deal.id, label=f"Deal: {deal.title}"
        )
    )
    return {"created_deal": _deal_view(deal)}


class MoveDealParams(BaseModel):
    deal_id: uuid.UUID
    stage_name: str = Field(description="Target pipeline stage, e.g. Proposal or Won")


async def move_deal(ctx: ToolContext, params: MoveDealParams) -> dict[str, Any]:
    deal = await ctx.deals.change_stage(params.deal_id, await _stage_id(ctx, params.stage_name))
    ctx.actions.append(
        AssistantAction(
            kind="moved",
            entity="deal",
            entity_id=deal.id,
            label=f"{deal.title} → {deal.stage.name}",
        )
    )
    return {"moved_deal": _deal_view(deal)}


# --- Team, reports and automations ---


async def list_users(ctx: ToolContext, _: NoParams) -> dict[str, Any]:
    page = await ctx.users.list_page(_page(100), None)
    return {
        "users": [
            {"id": str(u.id), "name": u.full_name, "email": u.email, "role": u.role}
            for u in page.items
            if u.is_active and u.email != SERVICE_ACCOUNT_EMAIL
        ],
        "current_user_id": str(ctx.user.id),
    }


async def get_dashboard_summary(ctx: ToolContext, _: NoParams) -> dict[str, Any]:
    summary = await ctx.dashboard.summary(ctx.user)
    overdue = await ctx.tasks.list_page(TaskFilters(overdue=True), _page())
    return {
        "open_pipeline_value": summary.open_pipeline_value,
        "won_this_month_value": summary.won_this_month_value,
        "new_leads_this_month": summary.new_leads_this_month,
        "overdue_tasks_all_users": summary.overdue_tasks,
        "overdue_task_list": [_task_view(t) for t in overdue.items],
        "pipeline_by_stage": [
            {"stage": s.stage_name, "deals": s.deal_count, "value": s.total_value}
            for s in summary.pipeline_by_stage
        ],
        "my_open_tasks_soonest_10": [_task_view(t) for t in summary.my_tasks],
        "recent_activities": [_activity_view(a) for a in summary.recent_activities],
    }


class ActivityListParams(BaseModel):
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None
    type: ActivityType | None = None
    search: str | None = None


async def list_activities(ctx: ToolContext, params: ActivityListParams) -> dict[str, Any]:
    page = await ctx.activities.list_page(ActivityFilters(**params.model_dump()), _page())
    return _listing("activities", page, _activity_view)


async def list_automations(ctx: ToolContext, _: NoParams) -> dict[str, Any]:
    if ctx.user.role != UserRole.ADMIN:
        raise PermissionDeniedError("Only admins can see automations")
    page = await ctx.webhooks.list_page(_page(50))
    return {
        "webhook_subscriptions": [
            {"event": w.event, "target_url": w.target_url, "active": w.is_active}
            for w in page.items
        ]
    }


# --- More updates ---


class UpdateDealParams(BaseModel):
    deal_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=200)
    value: Decimal | None = Field(default=None, ge=0)
    expected_close_date: date | None = None
    contact_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = Field(default=None, description="A teammate from list_users")


async def update_deal(ctx: ToolContext, params: UpdateDealParams) -> dict[str, Any]:
    changes = params.model_dump(exclude={"deal_id"}, exclude_none=True)
    deal = await ctx.deals.update(params.deal_id, DealUpdate(**changes))
    ctx.actions.append(
        AssistantAction(
            kind="updated", entity="deal", entity_id=deal.id, label=f"Updated {deal.title}"
        )
    )
    return {"updated_deal": _deal_view(deal)}


class UpdateCompanyParams(BaseModel):
    company_id: uuid.UUID
    name: str | None = Field(default=None, min_length=1, max_length=200)
    domain: str | None = None
    industry: str | None = None
    size: str | None = None
    website: str | None = None
    notes: str | None = None


async def update_company(ctx: ToolContext, params: UpdateCompanyParams) -> dict[str, Any]:
    changes = params.model_dump(exclude={"company_id"}, exclude_none=True)
    company = await ctx.companies.update(params.company_id, CompanyUpdate(**changes))
    ctx.actions.append(
        AssistantAction(
            kind="updated",
            entity="company",
            entity_id=company.id,
            label=f"Updated {company.name}",
        )
    )
    return {"updated_company": _company_view(company)}


# --- AI features and email ---


async def score_contact(ctx: ToolContext, params: ContactIdParams) -> dict[str, Any]:
    result = await ctx.ai_features.score_contact(params.contact_id)
    ctx.actions.append(
        AssistantAction(
            kind="scored",
            entity="contact",
            entity_id=params.contact_id,
            label=f"Lead score: {result.score}/100",
        )
    )
    return {"score": result.score, "reasoning": result.reasoning}


class SummarizeParams(BaseModel):
    contact_id: uuid.UUID | None = None
    deal_id: uuid.UUID | None = None


async def summarize_timeline(ctx: ToolContext, params: SummarizeParams) -> dict[str, Any]:
    summary = await ctx.ai_features.summarize(SummarizeRequest(**params.model_dump()))
    return summary.model_dump()


class DraftEmailParams(BaseModel):
    contact_id: uuid.UUID
    purpose: str = Field(min_length=1, max_length=1000, description="What the email should do")
    tone: str = "friendly"
    deal_id: uuid.UUID | None = None


async def draft_email(ctx: ToolContext, params: DraftEmailParams) -> dict[str, Any]:
    draft = await ctx.ai_features.draft_email(EmailDraftRequest(**params.model_dump()))
    return {"subject": draft.subject, "body": draft.body, "sent": False}


class SendEmailParams(BaseModel):
    contact_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    deal_id: uuid.UUID | None = None


async def send_email(ctx: ToolContext, params: SendEmailParams) -> dict[str, Any]:
    activity = await ctx.emails.send_to_contact(
        EmailSendRequest(**params.model_dump()), user=ctx.user
    )
    ctx.actions.append(
        AssistantAction(
            kind="sent",
            entity="activity",
            entity_id=activity.id,
            label=f"Email sent: {activity.subject}",
            **_link_for(activity.contact_id, activity.deal_id),
        )
    )
    return {"sent": True, "subject": activity.subject}


_TOOL_LIST = [
    Tool(
        "search_contacts",
        "Find or list contacts by name/email/phone, status, company or owner.",
        SearchContactsParams,
        search_contacts,
    ),
    Tool(
        "search_companies",
        "Find or list companies by name or industry.",
        SearchCompaniesParams,
        search_companies,
    ),
    Tool(
        "search_deals",
        "Find or list deals by title, stage, contact, company or owner.",
        SearchDealsParams,
        search_deals,
    ),
    Tool(
        "get_contact",
        "A contact's details with their deals, open tasks and recent activities.",
        ContactIdParams,
        get_contact,
    ),
    Tool(
        "get_deal",
        "A deal's details with its open tasks and recent activities.",
        DealIdParams,
        get_deal,
    ),
    Tool(
        "get_company",
        "A company's details with its contacts and deals.",
        CompanyIdParams,
        get_company,
    ),
    Tool(
        "list_tasks",
        "List open tasks for the whole team (default), the current user or a teammate; "
        "optionally overdue only or including done tasks.",
        ListTasksParams,
        list_tasks,
    ),
    Tool(
        "list_pipeline_stages",
        "The deal pipeline stage names, in order.",
        NoParams,
        list_pipeline_stages,
    ),
    Tool(
        "list_users",
        "Team members (to assign tasks/deals) and the current user's id.",
        NoParams,
        list_users,
    ),
    Tool(
        "get_dashboard_summary",
        "Same numbers as the dashboard: pipeline value, won this month, new leads, overdue "
        "tasks (whole team, with the list), deals per stage, my tasks, recent activities.",
        NoParams,
        get_dashboard_summary,
    ),
    Tool(
        "list_activities",
        "Recent notes, calls, emails and meetings (all, or for a contact/deal).",
        ActivityListParams,
        list_activities,
    ),
    Tool(
        "list_automations",
        "Admin only: the n8n webhook subscriptions (automations).",
        NoParams,
        list_automations,
    ),
    Tool("create_task", "Create a task / follow-up / reminder.", CreateTaskParams, create_task),
    Tool("complete_task", "Mark a task as done.", TaskIdParams, complete_task),
    Tool(
        "update_task",
        "Reschedule a task or change its title, priority or description.",
        UpdateTaskParams,
        update_task,
    ),
    Tool(
        "log_activity",
        "Log a note, call, email or meeting that happened, on a contact and/or deal.",
        LogActivityParams,
        log_activity,
    ),
    Tool("create_contact", "Create a new contact.", CreateContactParams, create_contact),
    Tool(
        "update_contact",
        "Change a contact's status, job title, email, phone, company, or add tags.",
        UpdateContactParams,
        update_contact,
    ),
    Tool("create_company", "Create a new company.", CreateCompanyParams, create_company),
    Tool("create_deal", "Create a new deal.", CreateDealParams, create_deal),
    Tool(
        "update_deal",
        "Change a deal's title, value, close date, contact, company or owner.",
        UpdateDealParams,
        update_deal,
    ),
    Tool(
        "update_company",
        "Change a company's name, domain, industry, size, website or notes.",
        UpdateCompanyParams,
        update_company,
    ),
    Tool(
        "score_contact",
        "AI lead score (0-100) for a contact; saved on the contact.",
        ContactIdParams,
        score_contact,
    ),
    Tool(
        "summarize_timeline",
        "AI summary and next actions for a contact's or deal's activity timeline.",
        SummarizeParams,
        summarize_timeline,
    ),
    Tool(
        "draft_email",
        "AI-written email draft for a contact. Does NOT send it.",
        DraftEmailParams,
        draft_email,
    ),
    Tool(
        "send_email",
        "Send an email to a contact (logged on their timeline). Only when the user clearly "
        "asked to send it.",
        SendEmailParams,
        send_email,
    ),
    Tool(
        "move_deal",
        "Move a deal to another pipeline stage (e.g. Won or Lost).",
        MoveDealParams,
        move_deal,
    ),
]

TOOLS: dict[str, Tool] = {tool.name: tool for tool in _TOOL_LIST}

TOOL_SPECS = [tool.spec() for tool in TOOLS.values()]
