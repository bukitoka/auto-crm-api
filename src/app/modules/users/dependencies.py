from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.core.storage import StorageDep
from app.modules.users.service import UserService


def get_user_service(session: SessionDep, storage: StorageDep) -> UserService:
    return UserService(session, storage)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
