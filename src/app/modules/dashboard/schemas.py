import uuid

from pydantic import BaseModel

from app.modules.activities.models import ActivityType
from app.modules.activities.schemas import ActivityRead
from app.modules.contacts.models import ContactStatus
from app.modules.deals.schemas import DealRead
from app.modules.tasks.schemas import TaskRead
from app.shared.schemas import UserRef


class StageSummary(BaseModel):
    stage_id: uuid.UUID
    stage_name: str
    deal_count: int
    total_value: float


class StatusCount(BaseModel):
    status: ContactStatus
    count: int


class ActivityTypeCount(BaseModel):
    type: ActivityType
    count: int


class TeamMemberStats(BaseModel):
    user: UserRef
    open_deals_value: float
    won_this_month_value: float
    open_tasks: int


class DashboardSummary(BaseModel):
    open_pipeline_value: float  # sum of deals in stages that are neither won nor lost
    won_this_month_value: float  # deals closed as won since the 1st of this month (UTC)
    deals_won_this_month: int
    deals_lost_this_month: int
    win_rate: float | None  # won / (won + lost) closed in the last 90 days; null if none closed
    average_deal_size: float | None  # mean value of deals won in the last 90 days
    new_leads_this_month: int  # contacts created since the 1st of this month (UTC)
    overdue_tasks: int  # all users' tasks due before today that are not done
    tasks_due_today: int  # all users' open tasks
    tasks_due_this_week: int  # all users' open tasks due today through the next 6 days
    pipeline_by_stage: list[StageSummary]  # every stage, in pipeline order
    contacts_by_status: list[StatusCount]  # every status, in lifecycle order
    activities_last_30_days: list[ActivityTypeCount]  # every activity type
    overdue_task_list: list[TaskRead]  # oldest due first (max 10)
    deals_closing_soon: list[DealRead]  # open deals expected to close in the next 30 days (max 10)
    team: list[TeamMemberStats]  # active users, most won this month first
    recent_activities: list[ActivityRead]  # latest 10
    my_tasks: list[TaskRead]  # current user's open tasks, soonest due first (max 10)
