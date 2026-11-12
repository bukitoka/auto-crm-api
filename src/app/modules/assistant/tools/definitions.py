"""Tool metadata, role access, and services shared by a single assistant reply."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import BaseMailer
from app.modules.activities.service import ActivityService
from app.modules.ai.client import AIClient
from app.modules.ai.service import AIService
from app.modules.assistant.blocks import AssistantBlock
from app.modules.assistant.schemas import AssistantAction
from app.modules.companies.service import CompanyService
from app.modules.contacts.service import ContactService
from app.modules.dashboard.service import DashboardService
from app.modules.deals.service import DealService
from app.modules.emails.service import EmailService
from app.modules.pipeline.repository import PipelineRepository
from app.modules.tasks.service import TaskService
from app.modules.users.models import User
from app.modules.users.service import UserService
from app.modules.webhooks.service import WebhookService

RESULT_LIMIT = 25


@dataclass
class ToolContext:
    """What every handler gets: services bound to this request, the user, and an action log."""

    session: AsyncSession
    user: User
    ai: AIClient
    mailer: BaseMailer
    actions: list[AssistantAction] = field(default_factory=list)
    blocks: list[AssistantBlock] = field(default_factory=list)

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


READ_TOOLS = frozenset(
    {
        "search_contacts",
        "search_companies",
        "search_deals",
        "get_contact",
        "get_deal",
        "get_company",
        "list_tasks",
        "list_pipeline_stages",
        "list_users",
        "get_dashboard_summary",
        "list_activities",
        "summarize_timeline",
        "get_monthly_trend",
        "show_chart",
        "show_metrics",
        "show_table",
    }
)


SUPERVISOR_TOOLS = frozenset({"list_automations", "create_admin", "set_admin_active"})


Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: type[BaseModel]
    handler: Handler

    @property
    def access(self) -> str:
        """Who may use it: "read" (everyone), "supervisor" (super admin only) or "work" (admins)."""
        if self.name in SUPERVISOR_TOOLS:
            return "supervisor"
        return "read" if self.name in READ_TOOLS else "work"

    def allowed_for(self, user: User) -> bool:
        if user.is_super_admin:
            return self.access != "work"
        return self.access != "supervisor"

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


class NoParams(BaseModel):
    pass
