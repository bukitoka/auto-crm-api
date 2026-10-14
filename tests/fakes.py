"""In-memory stand-ins for external services (object storage, SMTP).

Integration tests use them through FastAPI dependency overrides, so no test needs
MinIO or Mailpit running. The Newman e2e suite exercises the real services.
"""

from app.core.config import settings
from app.core.email import Mail, Mailer
from app.core.storage import Storage


class FakeStorage(Storage):
    """Keeps uploaded files in a dict. URLs are still signed locally (no network)."""

    def __init__(self) -> None:
        super().__init__(settings)
        self.files: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.files[key] = (data, content_type)

    async def delete(self, key: str) -> None:
        self.files.pop(key, None)


class FakeMailer(Mailer):
    """Records sent mail instead of talking to an SMTP server."""

    def __init__(self) -> None:
        super().__init__(settings)
        self.outbox: list[Mail] = []

    async def send(self, mail: Mail) -> None:
        self.build(mail)  # still check the message can be built
        self.outbox.append(mail)
