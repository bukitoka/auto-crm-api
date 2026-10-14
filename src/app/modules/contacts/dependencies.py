from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.core.storage import StorageDep
from app.modules.contacts.service import ContactService


def get_contact_service(session: SessionDep, storage: StorageDep) -> ContactService:
    return ContactService(session, storage)


ContactServiceDep = Annotated[ContactService, Depends(get_contact_service)]
