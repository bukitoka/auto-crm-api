from html import escape

from app.core.config import settings
from app.core.email import Mail
from app.modules.users.models import User


def password_reset_mail(user: User, token: str) -> Mail:
    link = f"{settings.frontend_url}/reset-password?token={token}"
    minutes = settings.password_reset_expire_minutes
    text = (
        f"Hi {user.full_name},\n\n"
        "Someone (hopefully you) asked to reset your Auto CRM password.\n"
        f"Open this link to choose a new one (valid for {minutes} minutes):\n\n"
        f"{link}\n\n"
        "If you didn't ask for this, you can ignore this email."
    )
    html = (
        f"<p>Hi {escape(user.full_name)},</p>"
        "<p>Someone (hopefully you) asked to reset your Auto CRM password.</p>"
        f'<p><a href="{escape(link)}">Choose a new password</a> '
        f"(the link is valid for {minutes} minutes).</p>"
        "<p>If you didn't ask for this, you can ignore this email.</p>"
    )
    return Mail(to=user.email, subject="Reset your Auto CRM password", text=text, html=html)
