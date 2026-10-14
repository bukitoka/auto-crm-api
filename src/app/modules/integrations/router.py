from fastapi import APIRouter, Response, status

from app.modules.auth.dependencies import ServiceAccount
from app.modules.contacts.schemas import ContactRead
from app.modules.integrations.dependencies import IntegrationServiceDep
from app.modules.integrations.schemas import LeadIntake

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.post(
    "/leads",
    response_model=ContactRead,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "A contact with this email already existed"}},
)
async def ingest_lead(
    service_account: ServiceAccount,
    data: LeadIntake,
    service: IntegrationServiceDep,
    response: Response,
):
    """API key only. Creates a lead contact (201) or reuses an existing one (200)."""
    contact, created = await service.ingest_lead(data, user=service_account)
    if not created:
        response.status_code = status.HTTP_200_OK
    return contact
