"""Search, read, and update contacts, companies, deals, and pipeline stages."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.core.exceptions import NotFoundError
from app.modules.activities.schemas import ActivityFilters
from app.modules.assistant.schemas import AssistantAction
from app.modules.assistant.tools.definitions import NoParams, ToolContext
from app.modules.assistant.tools.results import (
    _activity_view,
    _company_view,
    _contact_view,
    _deal_view,
    _listing,
    _name,
    _page,
    _task_view,
)
from app.modules.companies.schemas import (
    CompanyCreate,
    CompanyFilters,
    CompanyUpdate,
)
from app.modules.contacts.models import ContactStatus
from app.modules.contacts.schemas import ContactCreate, ContactFilters, ContactUpdate
from app.modules.deals.schemas import DealCreate, DealFilters, DealUpdate
from app.modules.tasks.schemas import TaskFilters


class SearchContactsParams(BaseModel):
    query: str | None = Field(default=None, description="Name, email or phone; omit to list all")
    status: ContactStatus | None = None
    company_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = Field(
        default=None, description="Your own user id (records stay with you)"
    )


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
    owner_id: uuid.UUID | None = Field(
        default=None, description="Your own user id (records stay with you)"
    )


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


async def list_pipeline_stages(ctx: ToolContext, _: NoParams) -> dict[str, Any]:
    stages = await ctx.pipeline.list_stages()
    return {"stages": [s.name for s in stages]}


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


class UpdateDealParams(BaseModel):
    deal_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=200)
    value: Decimal | None = Field(default=None, ge=0)
    expected_close_date: date | None = None
    contact_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = Field(
        default=None, description="Your own user id (records stay with you)"
    )


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
