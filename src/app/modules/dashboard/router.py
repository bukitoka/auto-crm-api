from fastapi import APIRouter

from app.modules.auth.dependencies import CurrentUser
from app.modules.dashboard.dependencies import DashboardServiceDep
from app.modules.dashboard.schemas import DashboardSummary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(service: DashboardServiceDep, user: CurrentUser):
    return await service.summary(user)
