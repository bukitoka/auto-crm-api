import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, UploadFile, status

from app.modules.auth.dependencies import CurrentUser, WorkingUser
from app.modules.contacts.dependencies import ContactServiceDep
from app.modules.contacts.schemas import (
    ContactCreate,
    ContactFilters,
    ContactRead,
    ContactUpdate,
)
from app.shared.csv_files import ImportResult, csv_response, read_csv
from app.shared.images import read_image
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=Page[ContactRead])
async def list_contacts(
    service: ContactServiceDep,
    _: CurrentUser,
    params: PageParamsDep,
    filters: Annotated[ContactFilters, Query()],
):
    return await service.list_page(filters, params)


@router.get("/export", response_class=Response)
async def export_contacts(
    service: ContactServiceDep, _: CurrentUser, filters: Annotated[ContactFilters, Query()]
):
    """All contacts matching the list filters and sort, as CSV."""
    return csv_response(await service.export_csv(filters), "contacts.csv")


@router.post("/import", response_model=ImportResult)
async def import_contacts(file: UploadFile, service: ContactServiceDep, user: WorkingUser):
    """Create contacts from a CSV file (max 2 MB) with the export's columns."""
    return await service.import_csv(await read_csv(file), user=user)


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
async def create_contact(data: ContactCreate, service: ContactServiceDep, user: WorkingUser):
    return await service.create(data, user=user)


@router.get("/{contact_id}", response_model=ContactRead)
async def get_contact(contact_id: uuid.UUID, service: ContactServiceDep, _: CurrentUser):
    return await service.get(contact_id)


@router.patch("/{contact_id}", response_model=ContactRead)
async def update_contact(
    contact_id: uuid.UUID, data: ContactUpdate, service: ContactServiceDep, _: WorkingUser
):
    return await service.update(contact_id, data)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(contact_id: uuid.UUID, service: ContactServiceDep, _: WorkingUser):
    await service.delete(contact_id)


@router.put("/{contact_id}/avatar", response_model=ContactRead)
async def upload_contact_avatar(
    contact_id: uuid.UUID, file: UploadFile, service: ContactServiceDep, _: WorkingUser
):
    """Upload a photo (JPEG, PNG, WebP or GIF, max 5 MB). Replaces the current one."""
    return await service.set_avatar(contact_id, await read_image(file))


@router.delete("/{contact_id}/avatar", response_model=ContactRead)
async def delete_contact_avatar(contact_id: uuid.UUID, service: ContactServiceDep, _: WorkingUser):
    return await service.remove_avatar(contact_id)
