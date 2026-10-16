from fastapi import APIRouter, status

from app.core.email import Mail, MailerDep
from app.modules.activities.schemas import ActivityRead
from app.modules.auth.dependencies import ServiceAccount, WorkingUser
from app.modules.emails.dependencies import EmailServiceDep
from app.modules.emails.schemas import EmailSendRequest, NotificationRequest

router = APIRouter(prefix="/emails", tags=["emails"])


@router.post("", response_model=ActivityRead, status_code=status.HTTP_201_CREATED)
async def send_email(data: EmailSendRequest, service: EmailServiceDep, user: WorkingUser):
    """Email a contact (replies go to you) and log it as an `email` activity."""
    return await service.send_to_contact(data, user=user)


@router.post("/notify", status_code=status.HTTP_204_NO_CONTENT)
async def notify(data: NotificationRequest, mailer: MailerDep, _: ServiceAccount):
    """Send a plain-text notice to team members. Automation API key only."""
    for recipient in data.to:
        await mailer.send(Mail(to=recipient, subject=data.subject, text=data.text))
