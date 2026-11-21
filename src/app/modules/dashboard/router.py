from fastapi import APIRouter

from app.core.database import SessionDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.dashboard.dependencies import DashboardServiceDep
from app.modules.dashboard.follow_ups import FollowUp, list_follow_ups
from app.modules.dashboard.schemas import DashboardSummary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(service: DashboardServiceDep, user: CurrentUser):
    return await service.summary(user)


@router.get("/follow-ups", response_model=list[FollowUp])
async def get_follow_ups(session: SessionDep, _: CurrentUser):
    return await list_follow_ups(session)
