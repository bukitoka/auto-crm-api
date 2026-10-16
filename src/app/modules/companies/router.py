import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, UploadFile, status

from app.modules.auth.dependencies import CurrentUser, WorkingUser
from app.modules.companies.dependencies import CompanyServiceDep
from app.modules.companies.schemas import (
    CompanyCreate,
    CompanyFilters,
    CompanyRead,
    CompanyUpdate,
)
from app.shared.csv_files import ImportResult, csv_response, read_csv
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


@router.get("/export", response_class=Response)
async def export_companies(
    service: CompanyServiceDep, _: CurrentUser, filters: Annotated[CompanyFilters, Query()]
):
    """All companies matching the list filters and sort, as CSV."""
    return csv_response(await service.export_csv(filters), "companies.csv")


@router.post("/import", response_model=ImportResult)
async def import_companies(file: UploadFile, service: CompanyServiceDep, user: WorkingUser):
    """Create companies from a CSV file (max 2 MB) with the export's columns."""
    return await service.import_csv(await read_csv(file), user=user)


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(data: CompanyCreate, service: CompanyServiceDep, user: WorkingUser):
    return await service.create(data, user=user)


@router.get("/{company_id}", response_model=CompanyRead)
async def get_company(company_id: uuid.UUID, service: CompanyServiceDep, _: CurrentUser):
    return await service.get(company_id)


@router.patch("/{company_id}", response_model=CompanyRead)
async def update_company(
    company_id: uuid.UUID, data: CompanyUpdate, service: CompanyServiceDep, _: WorkingUser
):
    return await service.update(company_id, data)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(company_id: uuid.UUID, service: CompanyServiceDep, _: WorkingUser):
    await service.delete(company_id)


@router.put("/{company_id}/logo", response_model=CompanyRead)
async def upload_company_logo(
    company_id: uuid.UUID, file: UploadFile, service: CompanyServiceDep, _: WorkingUser
):
    """Upload a logo (JPEG, PNG, WebP or GIF, max 5 MB). Replaces the current one."""
    return await service.set_logo(company_id, await read_image(file))


@router.delete("/{company_id}/logo", response_model=CompanyRead)
async def delete_company_logo(company_id: uuid.UUID, service: CompanyServiceDep, _: WorkingUser):
    return await service.remove_logo(company_id)
