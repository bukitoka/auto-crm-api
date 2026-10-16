import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.modules.auth.dependencies import CurrentUser, WorkingUser
from app.modules.deals.dependencies import DealServiceDep
from app.modules.deals.schemas import (
    DealCreate,
    DealFilters,
    DealRead,
    DealStageUpdate,
    DealUpdate,
)
from app.shared.csv_files import csv_response
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/deals", tags=["deals"])


@router.get("", response_model=Page[DealRead])
async def list_deals(
    service: DealServiceDep,
    _: CurrentUser,
    params: PageParamsDep,
    filters: Annotated[DealFilters, Query()],
):
    return await service.list_page(filters, params)


@router.get("/export", response_class=Response)
async def export_deals(
    service: DealServiceDep, _: CurrentUser, filters: Annotated[DealFilters, Query()]
):
    """All deals matching the list filters and sort, as CSV."""
    return csv_response(await service.export_csv(filters), "deals.csv")


@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
async def create_deal(data: DealCreate, service: DealServiceDep, user: WorkingUser):
    return await service.create(data, user=user)


@router.get("/{deal_id}", response_model=DealRead)
async def get_deal(deal_id: uuid.UUID, service: DealServiceDep, _: CurrentUser):
    return await service.get(deal_id)


@router.patch("/{deal_id}", response_model=DealRead)
async def update_deal(
    deal_id: uuid.UUID, data: DealUpdate, service: DealServiceDep, _: WorkingUser
):
    return await service.update(deal_id, data)


@router.patch("/{deal_id}/stage", response_model=DealRead)
async def change_deal_stage(
    deal_id: uuid.UUID, data: DealStageUpdate, service: DealServiceDep, _: WorkingUser
):
    return await service.change_stage(deal_id, data.stage_id)


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deal(deal_id: uuid.UUID, service: DealServiceDep, _: WorkingUser):
    await service.delete(deal_id)
