from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.modules.dashboard.service import DashboardService


def get_dashboard_service(session: SessionDep) -> DashboardService:
    return DashboardService(session)


DashboardServiceDep = Annotated[DashboardService, Depends(get_dashboard_service)]
