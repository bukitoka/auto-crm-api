from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.modules.activities.service import ActivityService


def get_activity_service(session: SessionDep) -> ActivityService:
    return ActivityService(session)


ActivityServiceDep = Annotated[ActivityService, Depends(get_activity_service)]
