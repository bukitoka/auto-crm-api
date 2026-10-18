"""Outgoing email: Brevo transactional API (official SDK), or SMTP to Mailpit in development."""

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from functools import lru_cache
from typing import Annotated

import httpx
from brevo import AsyncBrevo
from brevo.core.api_error import ApiError
from brevo.transactional_emails import (
    SendTransacEmailRequestReplyTo,
    SendTransacEmailRequestSender,
    SendTransacEmailRequestToItem,
)
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


class BaseMailer:
    async def send(self, mail: Mail) -> None:
        raise NotImplementedError


class BrevoMailer(BaseMailer):
    """Brevo transactional email API. The sender address must be verified in Brevo."""

    def __init__(self, config: Settings) -> None:
        self.config = config
        self._client = AsyncBrevo(
            api_key=config.brevo_api_key, timeout=config.brevo_timeout_seconds
        )

    async def send(self, mail: Mail) -> None:
        name, address = parseaddr(mail.to)
        try:
            await self._client.transactional_emails.send_transac_email(
                sender=SendTransacEmailRequestSender(
                    email=self.config.mail_from_email,
                    name=mail.from_name or self.config.mail_from_name,
                ),
                to=[SendTransacEmailRequestToItem(email=address, name=name or None)],
                subject=mail.subject,
                text_content=mail.text,
                html_content=mail.html,
                reply_to=self._reply_to(mail.reply_to),
            )
        except (ApiError, httpx.HTTPError) as exc:
            logger.exception("Sending email %r to %s failed", mail.subject, address)
            raise EmailDeliveryError() from exc

    @staticmethod
    def _reply_to(value: str | None) -> SendTransacEmailRequestReplyTo | None:
        if not value:
            return None
        name, address = parseaddr(value)
        return SendTransacEmailRequestReplyTo(email=address, name=name or None)


class SmtpMailer(BaseMailer):
    """Plain SMTP without auth or TLS, for a local catch-all inbox such as Mailpit."""

    def __init__(self, config: Settings) -> None:
        self.config = config

    async def send(self, mail: Mail) -> None:
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
        try:
            await asyncio.to_thread(self._send_sync, message)
        except (smtplib.SMTPException, OSError) as exc:
            logger.exception("Sending email %r to %s failed", mail.subject, mail.to)
            raise EmailDeliveryError() from exc

    def _send_sync(self, message: EmailMessage) -> None:
        # local_hostname skips socket.getfqdn(), which takes ~35 s on macOS.
        with smtplib.SMTP(
            self.config.smtp_host,
            self.config.smtp_port,
            local_hostname="localhost",
            timeout=self.config.smtp_timeout_seconds,
        ) as client:
            client.send_message(message)


@lru_cache
def get_mailer() -> BaseMailer:
    return SmtpMailer(settings) if settings.smtp_host else BrevoMailer(settings)


MailerDep = Annotated[BaseMailer, Depends(get_mailer)]
