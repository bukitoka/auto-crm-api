from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.modules.deals.service import DealService


def get_deal_service(session: SessionDep) -> DealService:
    return DealService(session)


DealServiceDep = Annotated[DealService, Depends(get_deal_service)]
