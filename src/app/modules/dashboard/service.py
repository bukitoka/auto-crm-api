from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activities.repository import ActivityRepository
from app.modules.activities.schemas import ActivityRead
from app.modules.dashboard.repository import DashboardRepository
from app.modules.dashboard.schemas import DashboardSummary, StageSummary
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskRead
from app.modules.users.models import User
from app.shared.utils import start_of_month_utc

RECENT_LIMIT = 10


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = DashboardRepository(session)
        self.activities = ActivityRepository(session)
        self.tasks = TaskRepository(session)

    async def summary(self, user: User) -> DashboardSummary:
        month_start = start_of_month_utc()
        stages = await self.repo.pipeline_by_stage()
        activities = await self.activities.list_recent(limit=RECENT_LIMIT)
        my_tasks = await self.tasks.list_open_for_assignee(user.id, limit=RECENT_LIMIT)

        return DashboardSummary(
            open_pipeline_value=float(await self.repo.open_pipeline_value()),
            won_this_month_value=float(await self.repo.won_value_since(month_start)),
            new_leads_this_month=await self.repo.contacts_created_since(month_start),
            overdue_tasks=await self.tasks.count_overdue(),
            pipeline_by_stage=[
                StageSummary(
                    stage_id=row.stage_id,
                    stage_name=row.stage_name,
                    deal_count=row.deal_count,
                    total_value=float(row.total_value),
                )
                for row in stages
            ],
            recent_activities=[ActivityRead.model_validate(a) for a in activities],
            my_tasks=[TaskRead.model_validate(t) for t in my_tasks],
        )
