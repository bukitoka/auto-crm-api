import uuid

from fastapi import APIRouter, UploadFile, status

from app.modules.auth.dependencies import CurrentUser, SuperAdminUser
from app.modules.users.dependencies import UserServiceDep
from app.modules.users.schemas import AdminCreate, UserRead, UserUpdate
from app.shared.images import read_image
from app.shared.pagination import Page, PageParamsDep

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserRead])
async def list_users(
    service: UserServiceDep,
    user: CurrentUser,
    params: PageParamsDep,
    search: str | None = None,
):
    return await service.list_page(params, search, viewer=user)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_admin(data: AdminCreate, service: UserServiceDep, _: SuperAdminUser):
    """Create an admin account. Only the super admin can."""
    return await service.create_admin(data)


@router.put("/me/avatar", response_model=UserRead)
async def upload_my_avatar(file: UploadFile, service: UserServiceDep, user: CurrentUser):
    """Upload your profile picture (JPEG, PNG, WebP or GIF, max 5 MB)."""
    return await service.set_avatar(user, await read_image(file))


@router.delete("/me/avatar", response_model=UserRead)
async def delete_my_avatar(service: UserServiceDep, user: CurrentUser):
    return await service.remove_avatar(user)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID, data: UserUpdate, service: UserServiceDep, _: SuperAdminUser
):
    """Edit an admin: name, email, password or on/off. Only the super admin can."""
    return await service.update(user_id, data)
