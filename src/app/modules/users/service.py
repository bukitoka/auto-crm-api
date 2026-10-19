import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password
from app.core.storage import Storage, get_storage
from app.modules.users.models import SERVICE_ACCOUNT_EMAIL, SERVICE_ACCOUNT_NAME, User, UserRole
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import AdminCreate, UserRead, UserUpdate
from app.shared.images import replace_image
from app.shared.pagination import Page, PageParams


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

    async def list_page(
        self, params: PageParams, search: str | None, *, viewer: User
    ) -> Page[UserRead]:
        """The super admin sees every admin; an admin sees only themselves."""
        items, total = await self.repo.list_page(
            search=search,
            only_id=None if viewer.is_super_admin else viewer.id,
            offset=params.offset,
            limit=params.size,
        )
        return Page[UserRead].from_items(items, total, params)

    async def create_admin(self, data: AdminCreate) -> User:
        return await self._create(data.email, data.password, data.full_name, role=UserRole.ADMIN)

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

    async def update(self, user_id: uuid.UUID, data: UserUpdate) -> User:
        user = await self.get(user_id)
        if user.is_super_admin or user.email == SERVICE_ACCOUNT_EMAIL:
            raise NotFoundError("User not found")
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        if "email" in changes:
            changes["email"] = changes["email"].lower()
            taken = await self.repo.get_by_email(changes["email"])
            if taken is not None and taken.id != user.id:
                raise ConflictError("A user with this email already exists")
        if "password" in changes:
            changes["hashed_password"] = hash_password(changes.pop("password"))
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
                role=UserRole.ADMIN,
            )
            await self.repo.add(user)
            await self.session.commit()
        return user
