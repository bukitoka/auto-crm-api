from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.modules.tasks.service import TaskService


def get_task_service(session: SessionDep) -> TaskService:
    return TaskService(session)


TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
