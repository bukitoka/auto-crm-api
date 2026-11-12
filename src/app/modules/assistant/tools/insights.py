"""Dashboard data, visual blocks, AI summaries, and email tools."""

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.modules.ai.schemas import EmailDraftRequest, SummarizeRequest
from app.modules.assistant.blocks import ChartBlock, MetricsBlock, TableBlock
from app.modules.assistant.schemas import AssistantAction
from app.modules.assistant.tools.definitions import NoParams, ToolContext
from app.modules.assistant.tools.records import ContactIdParams
from app.modules.assistant.tools.results import (
    _activity_view,
    _deal_view,
    _link_for,
    _page,
    _task_view,
)
from app.modules.dashboard.repository import TrendMetric
from app.modules.emails.schemas import EmailSendRequest
from app.modules.tasks.schemas import TaskFilters


class MonthlyTrendParams(BaseModel):
    metric: TrendMetric = Field(
        description="won_value (money from won deals), deals_won, new_contacts or new_deals"
    )
    months: int = Field(default=6, ge=2, le=12, description="How many calendar months, ending now")


async def get_monthly_trend(ctx: ToolContext, params: MonthlyTrendParams) -> dict[str, Any]:
    series = await ctx.dashboard.monthly_trend(params.metric, params.months)
    return {
        "metric": params.metric,
        "months": [{"month": month, "value": value} for month, value in series],
    }


_SHOWN = {"shown": True, "note": "It is displayed to the user under your reply."}


async def show_chart(ctx: ToolContext, params: ChartBlock) -> dict[str, Any]:
    ctx.blocks.append(params)
    return _SHOWN


async def show_metrics(ctx: ToolContext, params: MetricsBlock) -> dict[str, Any]:
    ctx.blocks.append(params)
    return _SHOWN


async def show_table(ctx: ToolContext, params: TableBlock) -> dict[str, Any]:
    ctx.blocks.append(params)
    return _SHOWN


async def get_dashboard_summary(ctx: ToolContext, _: NoParams) -> dict[str, Any]:
    summary = await ctx.dashboard.summary(ctx.user)
    overdue = await ctx.tasks.list_page(TaskFilters(overdue=True), _page())
    return {
        "open_pipeline_value": summary.open_pipeline_value,
        "won_this_month_value": summary.won_this_month_value,
        "deals_won_this_month": summary.deals_won_this_month,
        "deals_lost_this_month": summary.deals_lost_this_month,
        "win_rate_last_90_days": summary.win_rate,
        "average_won_deal_size_last_90_days": summary.average_deal_size,
        "new_leads_this_month": summary.new_leads_this_month,
        "overdue_tasks": summary.overdue_tasks,
        "overdue_task_list": [_task_view(task) for task in overdue.items],
        "tasks_due_today": summary.tasks_due_today,
        "tasks_due_next_7_days": summary.tasks_due_this_week,
        "pipeline_by_stage": [
            {"stage": stage.stage_name, "deals": stage.deal_count, "value": stage.total_value}
            for stage in summary.pipeline_by_stage
        ],
        "contacts_by_status": {
            status.status: status.count for status in summary.contacts_by_status
        },
        "activities_last_30_days": {
            activity.type: activity.count for activity in summary.activities_last_30_days
        },
        "deals_closing_next_30_days": [_deal_view(deal) for deal in summary.deals_closing_soon],
        "team": [
            {
                "name": member.user.full_name,
                "open_deals_value": member.open_deals_value,
                "won_this_month_value": member.won_this_month_value,
                "open_tasks": member.open_tasks,
            }
            for member in summary.team
        ],
        "my_open_tasks_soonest_10": [_task_view(task) for task in summary.my_tasks],
        "recent_activities": [_activity_view(activity) for activity in summary.recent_activities],
    }


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
