"""In-memory stand-ins for external services (object storage, email).

Integration tests use them through FastAPI dependency overrides, so no test needs
MinIO or Brevo access. The Newman e2e suite exercises the real services.
"""

from app.core.config import settings
from app.core.email import BaseMailer, Mail
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


class FakeMailer(BaseMailer):
    """Records sent mail instead of calling Brevo."""

    def __init__(self) -> None:
        self.outbox: list[Mail] = []

    async def send(self, mail: Mail) -> None:
        self.outbox.append(mail)
