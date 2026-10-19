from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activities.models import ActivityType
from app.modules.activities.repository import ActivityRepository
from app.modules.activities.schemas import ActivityRead
from app.modules.contacts.models import ContactStatus
from app.modules.dashboard.repository import DashboardRepository, TrendMetric
from app.modules.dashboard.schemas import (
    ActivityTypeCount,
    DashboardSummary,
    StageSummary,
    StatusCount,
    TeamMemberStats,
)
from app.modules.deals.schemas import DealRead
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.schemas import TaskRead
from app.modules.users.models import User
from app.shared.schemas import UserRef
from app.shared.utils import start_of_month_utc, today_utc, utc_now

RECENT_LIMIT = 10
WIN_RATE_DAYS = 90
ACTIVITY_DAYS = 30
CLOSING_SOON_DAYS = 30


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = DashboardRepository(session)
        self.activities = ActivityRepository(session)
        self.tasks = TaskRepository(session)

    async def monthly_trend(self, metric: TrendMetric, months: int) -> list[tuple[str, float]]:
        """The last `months` calendar months, oldest first, zero where nothing happened."""
        first = start_of_month_utc()
        starts = []
        year, month = first.year, first.month
        for _ in range(months):
            starts.append((year, month))
            year, month = (year, month - 1) if month > 1 else (year - 1, 12)
        starts.reverse()
        since = first.replace(year=starts[0][0], month=starts[0][1])
        totals = await self.repo.monthly_totals(metric, since)
        return [(f"{y}-{m:02d}", totals.get(f"{y}-{m:02d}", 0.0)) for y, m in starts]

    async def summary(self, user: User) -> DashboardSummary:
        month_start = start_of_month_utc()
        today = today_utc()
        month = await self.repo.closed_deals_since(month_start)
        recent = await self.repo.closed_deals_since(utc_now() - timedelta(days=WIN_RATE_DAYS))
        closed = recent.won_count + recent.lost_count
        stages = await self.repo.pipeline_by_stage()
        statuses = await self.repo.contacts_by_status()
        activity_types = await self.repo.activities_by_type_since(
            utc_now() - timedelta(days=ACTIVITY_DAYS)
        )
        closing_soon = await self.repo.open_deals_closing_between(
            today, today + timedelta(days=CLOSING_SOON_DAYS), limit=RECENT_LIMIT
        )
        team = await self.repo.leaderboard(
            month_start, only_id=None if user.is_super_admin else user.id
        )
        activities = await self.activities.list_recent(limit=RECENT_LIMIT)
        my_tasks = await self.tasks.list_open_for_assignee(user.id, limit=RECENT_LIMIT)

        return DashboardSummary(
            open_pipeline_value=float(await self.repo.open_pipeline_value()),
            won_this_month_value=float(month.won_value),
            deals_won_this_month=month.won_count,
            deals_lost_this_month=month.lost_count,
            win_rate=recent.won_count / closed if closed else None,
            average_deal_size=(
                float(recent.won_value) / recent.won_count if recent.won_count else None
            ),
            new_leads_this_month=await self.repo.contacts_created_since(month_start),
            overdue_tasks=await self.tasks.count_overdue(),
            tasks_due_today=await self.repo.open_tasks_due_between(today, today),
            tasks_due_this_week=await self.repo.open_tasks_due_between(
                today, today + timedelta(days=6)
            ),
            pipeline_by_stage=[
                StageSummary(
                    stage_id=row.stage_id,
                    stage_name=row.stage_name,
                    deal_count=row.deal_count,
                    total_value=float(row.total_value),
                )
                for row in stages
            ],
            contacts_by_status=[
                StatusCount(status=s, count=statuses.get(s, 0)) for s in ContactStatus
            ],
            activities_last_30_days=[
                ActivityTypeCount(type=t, count=activity_types.get(t, 0)) for t in ActivityType
            ],
            overdue_task_list=[
                TaskRead.model_validate(t)
                for t in await self.repo.overdue_tasks(today, limit=RECENT_LIMIT)
            ],
            deals_closing_soon=[DealRead.model_validate(d) for d in closing_soon],
            team=[
                TeamMemberStats(
                    user=UserRef.model_validate(row.User),
                    open_deals_value=float(row.open_deals_value),
                    won_this_month_value=float(row.won_this_month_value),
                    open_tasks=row.open_tasks,
                )
                for row in team
            ],
            recent_activities=[ActivityRead.model_validate(a) for a in activities],
            my_tasks=[TaskRead.model_validate(t) for t in my_tasks],
        )
