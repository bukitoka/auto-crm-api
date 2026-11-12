"""Explicit assistant tool registry.

Add a handler and its argument model in the relevant module, then register it here.
"""

from typing import Any

from app.modules.assistant.blocks import ChartBlock, MetricsBlock, TableBlock
from app.modules.assistant.tools.administration import (
    CreateAdminParams,
    SetAdminActiveParams,
    create_admin,
    list_automations,
    list_users,
    set_admin_active,
)
from app.modules.assistant.tools.definitions import NoParams, Tool
from app.modules.assistant.tools.definitions import ToolContext as ToolContext
from app.modules.assistant.tools.insights import (
    DraftEmailParams,
    MonthlyTrendParams,
    SendEmailParams,
    SummarizeParams,
    draft_email,
    get_dashboard_summary,
    get_monthly_trend,
    score_contact,
    send_email,
    show_chart,
    show_metrics,
    show_table,
    summarize_timeline,
)
from app.modules.assistant.tools.records import (
    CompanyIdParams,
    ContactIdParams,
    CreateCompanyParams,
    CreateContactParams,
    CreateDealParams,
    DealIdParams,
    MoveDealParams,
    SearchCompaniesParams,
    SearchContactsParams,
    SearchDealsParams,
    UpdateCompanyParams,
    UpdateContactParams,
    UpdateDealParams,
    create_company,
    create_contact,
    create_deal,
    get_company,
    get_contact,
    get_deal,
    list_pipeline_stages,
    move_deal,
    search_companies,
    search_contacts,
    search_deals,
    update_company,
    update_contact,
    update_deal,
)
from app.modules.assistant.tools.tasks import (
    ActivityListParams,
    CreateTaskParams,
    ListTasksParams,
    LogActivityParams,
    TaskIdParams,
    UpdateTaskParams,
    complete_task,
    create_task,
    list_activities,
    list_tasks,
    log_activity,
    update_task,
)
from app.modules.users.models import User

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
        "List open tasks you can see (default), the current user's or one admin's; "
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
        "The admin accounts you can see and the current user's id.",
        NoParams,
        list_users,
    ),
    Tool(
        "get_dashboard_summary",
        "Same numbers as the dashboard: pipeline value, won/lost this month, win rate, average "
        "deal size, new leads, overdue and due tasks (with the list), deals per "
        "stage, deals closing soon, leads by status, activity counts, admin leaderboard, my "
        "tasks, recent activities.",
        NoParams,
        get_dashboard_summary,
    ),
    Tool(
        "get_monthly_trend",
        "Totals per calendar month for the last 2-12 months: money from won deals, deals won, "
        "new contacts or new deals. Use it for trend questions, then draw it with show_chart.",
        MonthlyTrendParams,
        get_monthly_trend,
    ),
    Tool(
        "show_chart",
        "Draw a bar, line or pie chart under your reply from numbers you already fetched with "
        "the other tools. The title must be the question it answers. Use line for change over "
        "time, bar to compare, pie for shares of a whole. Never chart numbers you made up.",
        ChartBlock,
        show_chart,
    ),
    Tool(
        "show_metrics",
        "Show up to 6 headline numbers as cards under your reply. Values are pre-formatted text.",
        MetricsBlock,
        show_metrics,
    ),
    Tool(
        "show_table",
        "Show a table (up to 25 rows, 6 columns) under your reply. Add row_links so a row opens "
        "its contact, company or deal.",
        TableBlock,
        show_table,
    ),
    Tool(
        "list_activities",
        "Recent notes, calls, emails and meetings (all, or for a contact/deal).",
        ActivityListParams,
        list_activities,
    ),
    Tool(
        "list_automations",
        "Super admin only: the n8n webhook subscriptions (automations).",
        NoParams,
        list_automations,
    ),
    Tool(
        "create_admin",
        "Super admin only: create an admin account. Returns a temporary password to hand over.",
        CreateAdminParams,
        create_admin,
    ),
    Tool(
        "set_admin_active",
        "Super admin only: activate or deactivate an admin account.",
        SetAdminActiveParams,
        set_admin_active,
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


def tool_specs_for(user: User) -> list[dict[str, Any]]:
    """The tools this user's assistant may call: admins do CRM work, the super admin supervises."""
    return [tool.spec() for tool in TOOLS.values() if tool.allowed_for(user)]
