from typing import Annotated

from fastapi import Depends

from app.core.database import SessionDep
from app.core.email import MailerDep
from app.modules.emails.service import EmailService


def get_email_service(session: SessionDep, mailer: MailerDep) -> EmailService:
    return EmailService(session, mailer)


EmailServiceDep = Annotated[EmailService, Depends(get_email_service)]
