import uuid

from pydantic import BaseModel

from app.modules.activities.schemas import ActivityRead
from app.modules.tasks.schemas import TaskRead


class StageSummary(BaseModel):
    stage_id: uuid.UUID
    stage_name: str
    deal_count: int
    total_value: float


class DashboardSummary(BaseModel):
    open_pipeline_value: float  # sum of deals in stages that are neither won nor lost
    won_this_month_value: float  # deals closed as won since the 1st of this month (UTC)
    new_leads_this_month: int  # contacts created since the 1st of this month (UTC)
    overdue_tasks: int  # all users' tasks due before today that are not done
    pipeline_by_stage: list[StageSummary]  # every stage, in pipeline order
    recent_activities: list[ActivityRead]  # latest 10
    my_tasks: list[TaskRead]  # current user's open tasks, soonest due first (max 10)
