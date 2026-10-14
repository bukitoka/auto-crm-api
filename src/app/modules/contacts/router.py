import uuid
from typing import Annotated

from fastapi import APIRouter, Query, UploadFile, status

from app.modules.auth.dependencies import CurrentUser
from app.modules.contacts.dependencies import ContactServiceDep
from app.modules.contacts.schemas import (
    ContactCreate,
    ContactFilters,
    ContactRead,
    ContactUpdate,
)
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


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
async def create_contact(data: ContactCreate, service: ContactServiceDep, user: CurrentUser):
    return await service.create(data, user=user)


@router.get("/{contact_id}", response_model=ContactRead)
async def get_contact(contact_id: uuid.UUID, service: ContactServiceDep, _: CurrentUser):
    return await service.get(contact_id)


@router.patch("/{contact_id}", response_model=ContactRead)
async def update_contact(
    contact_id: uuid.UUID, data: ContactUpdate, service: ContactServiceDep, _: CurrentUser
):
    return await service.update(contact_id, data)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(contact_id: uuid.UUID, service: ContactServiceDep, _: CurrentUser):
    await service.delete(contact_id)


@router.put("/{contact_id}/avatar", response_model=ContactRead)
async def upload_contact_avatar(
    contact_id: uuid.UUID, file: UploadFile, service: ContactServiceDep, _: CurrentUser
):
    """Upload a photo (JPEG, PNG, WebP or GIF, max 5 MB). Replaces the current one."""
    return await service.set_avatar(contact_id, await read_image(file))


@router.delete("/{contact_id}/avatar", response_model=ContactRead)
async def delete_contact_avatar(contact_id: uuid.UUID, service: ContactServiceDep, _: CurrentUser):
    return await service.remove_avatar(contact_id)
