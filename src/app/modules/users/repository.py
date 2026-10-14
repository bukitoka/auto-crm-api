import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User
from app.shared.utils import like_pattern


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def count_excluding(self, email: str) -> int:
        """Count users, ignoring one email (used to skip the service account)."""
        result = await self.session.execute(
            select(func.count()).select_from(User).where(User.email != email)
        )
        return result.scalar_one()

    async def list_page(
        self, *, search: str | None, offset: int, limit: int
    ) -> tuple[list[User], int]:
        query = select(User)
        if search:
            pattern = like_pattern(search)
            query = query.where(or_(User.full_name.ilike(pattern), User.email.ilike(pattern)))

        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        result = await self.session.execute(
            query.order_by(User.full_name).offset(offset).limit(limit)
        )
        return list(result.scalars()), total or 0

    async def add(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user
