from email.utils import formataddr

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import Mail, Mailer, get_mailer
from app.core.exceptions import BadRequestError
from app.modules.activities.models import Activity, ActivityType
from app.modules.activities.schemas import ActivityCreate
from app.modules.activities.service import ActivityService
from app.modules.contacts.service import ContactService
from app.modules.emails.schemas import EmailSendRequest
from app.modules.users.models import User


class EmailService:
    """Sends emails to contacts and logs each one on the contact's timeline."""

    def __init__(self, session: AsyncSession, mailer: Mailer | None = None) -> None:
        self.contacts = ContactService(session)
        self.activities = ActivityService(session)
        self.mailer = mailer or get_mailer()

    async def send_to_contact(self, data: EmailSendRequest, *, user: User) -> Activity:
        contact = await self.contacts.get(data.contact_id)
        if not contact.email:
            raise BadRequestError("This contact has no email address")

        full_name = " ".join(filter(None, [contact.first_name, contact.last_name]))
        await self.mailer.send(
            Mail(
                to=formataddr((full_name, contact.email)),
                subject=data.subject,
                text=data.body,
                from_name=f"{user.full_name} via Auto CRM",
                reply_to=formataddr((user.full_name, user.email)),  # replies go to the sender
            )
        )
        # Only logged once the email was actually sent.
        return await self.activities.create(
            ActivityCreate(
                type=ActivityType.EMAIL,
                subject=data.subject,
                body=data.body,
                contact_id=contact.id,
                deal_id=data.deal_id,
            ),
            user=user,
        )
