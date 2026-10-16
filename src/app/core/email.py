"""In development every message lands in Mailpit (http://localhost:8026) instead of a
real inbox. In production, point the SMTP_* settings at your email provider.
"""

import logging
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from functools import lru_cache
from typing import Annotated

import aiosmtplib
from fastapi import Depends

from app.core.config import Settings, settings
from app.core.exceptions import EmailDeliveryError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Mail:
    to: str  # "jane@example.com" or "Jane Doe <jane@example.com>"
    subject: str
    text: str
    html: str | None = None  # optional HTML version of `text`
    reply_to: str | None = None
    from_name: str | None = None  # defaults to MAIL_FROM_NAME


class Mailer:
    def __init__(self, config: Settings) -> None:
        self.config = config

    def build(self, mail: Mail) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr(
            (mail.from_name or self.config.mail_from_name, self.config.mail_from_email)
        )
        message["To"] = mail.to
        message["Subject"] = mail.subject
        if mail.reply_to:
            message["Reply-To"] = mail.reply_to
        message.set_content(mail.text)
        if mail.html:
            message.add_alternative(mail.html, subtype="html")
        return message

    async def send(self, mail: Mail) -> None:
        config = self.config
        try:
            await aiosmtplib.send(
                self.build(mail),
                hostname=config.smtp_host,
                port=config.smtp_port,
                username=config.smtp_username or None,
                password=config.smtp_password or None,
                start_tls=config.smtp_starttls,
                timeout=config.smtp_timeout_seconds,
                # The name we greet the server with (EHLO). Without it aiosmtplib calls
                # socket.getfqdn(), which can block for 30+ seconds on some machines.
                local_hostname=config.mail_from_email.rpartition("@")[2],
            )
        except (aiosmtplib.SMTPException, OSError) as exc:
            logger.exception("Sending email %r to %s failed", mail.subject, mail.to)
            raise EmailDeliveryError() from exc


@lru_cache
def get_mailer() -> Mailer:
    return Mailer(settings)


MailerDep = Annotated[Mailer, Depends(get_mailer)]
