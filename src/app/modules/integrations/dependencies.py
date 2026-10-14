from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.modules.integrations.service import IntegrationService


def get_integration_service(session: SessionDep) -> IntegrationService:
    return IntegrationService(session)


IntegrationServiceDep = Annotated[IntegrationService, Depends(get_integration_service)]
