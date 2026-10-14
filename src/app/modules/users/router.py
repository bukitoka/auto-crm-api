import uuid

from fastapi import APIRouter, UploadFile

from app.modules.auth.dependencies import AdminUser, CurrentUser
from app.modules.users.dependencies import UserServiceDep
from app.modules.users.schemas import UserRead, UserUpdate
from app.shared.images import read_image
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserRead])
async def list_users(
    service: UserServiceDep,
    _: CurrentUser,
    params: PageParamsDep,
    search: str | None = None,
):
    return await service.list_page(params, search)


@router.put("/me/avatar", response_model=UserRead)
async def upload_my_avatar(file: UploadFile, service: UserServiceDep, user: CurrentUser):
    """Upload your profile picture (JPEG, PNG, WebP or GIF, max 5 MB)."""
    return await service.set_avatar(user, await read_image(file))


@router.delete("/me/avatar", response_model=UserRead)
async def delete_my_avatar(service: UserServiceDep, user: CurrentUser):
    return await service.remove_avatar(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID, data: UserUpdate, service: UserServiceDep, admin: AdminUser
):
    return await service.update(user_id, data, acting_user=admin)
