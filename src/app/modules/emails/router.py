from fastapi import APIRouter, status

from app.modules.activities.schemas import ActivityRead
from app.modules.auth.dependencies import CurrentUser
from app.modules.emails.dependencies import EmailServiceDep
from app.modules.emails.schemas import EmailSendRequest

router = APIRouter(prefix="/emails", tags=["emails"])


@router.post("", response_model=ActivityRead, status_code=status.HTTP_201_CREATED)
async def send_email(data: EmailSendRequest, service: EmailServiceDep, user: CurrentUser):
    """Email a contact (replies go to you) and log it as an `email` activity."""
    return await service.send_to_contact(data, user=user)
