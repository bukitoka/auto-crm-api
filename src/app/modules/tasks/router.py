import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.modules.auth.dependencies import CurrentUser
from app.modules.tasks.dependencies import TaskServiceDep
from app.modules.tasks.schemas import TaskCreate, TaskFilters, TaskRead, TaskUpdate
from app.shared.csv_files import csv_response
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=Page[TaskRead])
async def list_tasks(
    service: TaskServiceDep,
    _: CurrentUser,
    params: PageParamsDep,
    filters: Annotated[TaskFilters, Query()],
):
    return await service.list_page(filters, params)


@router.get("/export", response_class=Response)
async def export_tasks(
    service: TaskServiceDep, _: CurrentUser, filters: Annotated[TaskFilters, Query()]
):
    """All tasks matching the list filters and sort, as CSV."""
    return csv_response(await service.export_csv(filters), "tasks.csv")


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(data: TaskCreate, service: TaskServiceDep, user: CurrentUser):
    return await service.create(data, user=user)


@router.get("/{task_id}", response_model=TaskRead)
async def get_task(task_id: uuid.UUID, service: TaskServiceDep, _: CurrentUser):
    return await service.get(task_id)


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: uuid.UUID, data: TaskUpdate, service: TaskServiceDep, _: CurrentUser
):
    return await service.update(task_id, data)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: uuid.UUID, service: TaskServiceDep, _: CurrentUser):
    await service.delete(task_id)
