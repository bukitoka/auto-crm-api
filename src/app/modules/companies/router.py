import uuid
from typing import Annotated

from fastapi import APIRouter, Query, UploadFile, status

from app.modules.auth.dependencies import CurrentUser
from app.modules.companies.dependencies import CompanyServiceDep
from app.modules.companies.schemas import (
    CompanyCreate,
    CompanyFilters,
    CompanyRead,
    CompanyUpdate,
)
from app.shared.images import read_image
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=Page[CompanyRead])
async def list_companies(
    service: CompanyServiceDep,
    _: CurrentUser,
    params: PageParamsDep,
    filters: Annotated[CompanyFilters, Query()],
):
    return await service.list_page(filters, params)


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(data: CompanyCreate, service: CompanyServiceDep, user: CurrentUser):
    return await service.create(data, user=user)


@router.get("/{company_id}", response_model=CompanyRead)
async def get_company(company_id: uuid.UUID, service: CompanyServiceDep, _: CurrentUser):
    return await service.get(company_id)


@router.patch("/{company_id}", response_model=CompanyRead)
async def update_company(
    company_id: uuid.UUID, data: CompanyUpdate, service: CompanyServiceDep, _: CurrentUser
):
    return await service.update(company_id, data)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(company_id: uuid.UUID, service: CompanyServiceDep, _: CurrentUser):
    await service.delete(company_id)


@router.put("/{company_id}/logo", response_model=CompanyRead)
async def upload_company_logo(
    company_id: uuid.UUID, file: UploadFile, service: CompanyServiceDep, _: CurrentUser
):
    """Upload a logo (JPEG, PNG, WebP or GIF, max 5 MB). Replaces the current one."""
    return await service.set_logo(company_id, await read_image(file))


@router.delete("/{company_id}/logo", response_model=CompanyRead)
async def delete_company_logo(company_id: uuid.UUID, service: CompanyServiceDep, _: CurrentUser):
    return await service.remove_logo(company_id)
