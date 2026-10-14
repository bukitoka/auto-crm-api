from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.core.storage import StorageDep
from app.modules.companies.service import CompanyService


def get_company_service(session: SessionDep, storage: StorageDep) -> CompanyService:
    return CompanyService(session, storage)


CompanyServiceDep = Annotated[CompanyService, Depends(get_company_service)]
