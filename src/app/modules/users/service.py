import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.security import hash_password
from app.core.storage import Storage, get_storage
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserRead, UserUpdate
from app.shared.images import replace_image
from app.shared.pagination import Page, PageParams

# The X-API-Key (n8n) acts as this user, so created records have an author.
SERVICE_ACCOUNT_EMAIL = "automation@auto-crm.local"
SERVICE_ACCOUNT_NAME = "Automation (n8n)"


class UserService:
    def __init__(self, session: AsyncSession, storage: Storage | None = None) -> None:
        self.session = session
        self.storage = storage or get_storage()
        self.repo = UserRepository(session)

    async def get(self, user_id: uuid.UUID) -> User:
        user = await self.repo.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    async def list_page(self, params: PageParams, search: str | None) -> Page[UserRead]:
        items, total = await self.repo.list_page(
            search=search, offset=params.offset, limit=params.size
        )
        return Page[UserRead].from_items(items, total, params)

    async def create(self, *, email: str, password: str, full_name: str) -> User:
        """Create a team member. The super admin decides who becomes an admin."""
        if not await self.repo.super_admin_exists():
            raise PermissionDeniedError("Finish setting up the workspace first")
        return await self._create(email, password, full_name, role=UserRole.MEMBER)

    async def setup(self, *, email: str, password: str, full_name: str) -> User:
        """Create the first super admin. Works only once, on a workspace without one."""
        if await self.repo.super_admin_exists():
            raise ConflictError("The workspace is already set up")
        return await self.create_super_admin(email=email, password=password, full_name=full_name)

    async def create_super_admin(self, *, email: str, password: str, full_name: str) -> User:
        return await self._create(email, password, full_name, role=UserRole.ADMIN, super_admin=True)

    async def set_password(self, email: str, password: str) -> User:
        user = await self.repo.get_by_email(email)
        if user is None or user.email == SERVICE_ACCOUNT_EMAIL:
            raise NotFoundError("User not found")
        user.hashed_password = hash_password(password)
        await self.session.commit()
        return user

    async def _create(
        self,
        email: str,
        password: str,
        full_name: str,
        *,
        role: UserRole,
        super_admin: bool = False,
    ) -> User:
        email = email.lower()
        if await self.repo.get_by_email(email):
            raise ConflictError("A user with this email already exists")
        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=role,
            is_super_admin=super_admin,
        )
        await self.repo.add(user)
        await self.session.commit()
        return user

    async def update(self, user_id: uuid.UUID, data: UserUpdate, *, acting_user: User) -> User:
        user = await self.get(user_id)
        if user.is_super_admin:
            # Not part of the team, so not managed from the Team page.
            raise NotFoundError("User not found")
        changes = data.model_dump(exclude_unset=True, exclude_none=True)

        new_role = changes.get("role", user.role)
        role_changed = new_role != user.role
        demotes_or_deactivates = role_changed or changes.get("is_active") is False

        if user.id == acting_user.id and demotes_or_deactivates:
            raise BadRequestError("You cannot change your own role or deactivate yourself")
        # Admins manage members; only the super admin can touch other admins or make someone admin.
        if not acting_user.is_super_admin and (
            (user.role == UserRole.ADMIN and user.id != acting_user.id)
            or (role_changed and new_role == UserRole.ADMIN)
        ):
            raise PermissionDeniedError("Only the super admin can manage admins")

        for field, value in changes.items():
            setattr(user, field, value)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def set_avatar(self, user: User, image: bytes) -> User:
        """Store a new avatar (already converted by `read_image`) for `user`."""
        user.avatar_key = await replace_image(
            self.storage, folder=f"users/{user.id}", image=image, old_key=user.avatar_key
        )
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def remove_avatar(self, user: User) -> User:
        if user.avatar_key:
            old_key, user.avatar_key = user.avatar_key, None
            await self.session.commit()
            await self.session.refresh(user)
            await self.storage.delete(old_key)
        return user

    async def get_or_create_service_account(self) -> User:
        user = await self.repo.get_by_email(SERVICE_ACCOUNT_EMAIL)
        if user is None:
            user = User(
                email=SERVICE_ACCOUNT_EMAIL,
                # Random, never shared: nobody can log in as the service account.
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                full_name=SERVICE_ACCOUNT_NAME,
                role=UserRole.MEMBER,
            )
            await self.repo.add(user)
            await self.session.commit()
        return user
