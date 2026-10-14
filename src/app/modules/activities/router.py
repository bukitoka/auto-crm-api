import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.modules.activities.dependencies import ActivityServiceDep
from app.modules.activities.schemas import ActivityCreate, ActivityFilters, ActivityRead
from app.modules.auth.dependencies import CurrentUser
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("", response_model=Page[ActivityRead])
async def list_activities(
    service: ActivityServiceDep,
    _: CurrentUser,
    params: PageParamsDep,
    filters: Annotated[ActivityFilters, Query()],
):
    return await service.list_page(filters, params)


@router.post("", response_model=ActivityRead, status_code=status.HTTP_201_CREATED)
async def create_activity(data: ActivityCreate, service: ActivityServiceDep, user: CurrentUser):
    return await service.create(data, user=user)


@router.delete("/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_activity(activity_id: uuid.UUID, service: ActivityServiceDep, _: CurrentUser):
    await service.delete(activity_id)
