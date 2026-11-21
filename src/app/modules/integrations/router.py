from fastapi import APIRouter, Response, status
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionDep
from app.modules.auth.dependencies import ServiceAccount, SuperAdminUser
from app.modules.contacts.schemas import ContactRead
from app.modules.integrations.dependencies import IntegrationServiceDep
from app.modules.integrations.models import LeadRouting
from app.modules.integrations.schemas import LeadIntake, LeadRoutingSettings

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


@router.get("/lead-routing", response_model=LeadRoutingSettings)
async def lead_routing_settings(_: SuperAdminUser, session: SessionDep):
    current = await session.get(LeadRouting, 1)
    if current is None:
        return LeadRoutingSettings()
    return LeadRoutingSettings(enabled=current.enabled, response_hours=current.response_hours)


@router.put("/lead-routing", response_model=LeadRoutingSettings)
async def save_lead_routing(data: LeadRoutingSettings, _: SuperAdminUser, session: SessionDep):
    values = data.model_dump()
    await session.execute(
        insert(LeadRouting)
        .values(id=1, **values)
        .on_conflict_do_update(index_elements=["id"], set_=values)
    )
    await session.commit()
    return data
