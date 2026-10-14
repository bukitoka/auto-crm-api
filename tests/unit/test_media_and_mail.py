"""Images (Pillow), object storage (MinIO SDK) and SMTP, all without real services."""

import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiosmtplib
import pytest
from fastapi import UploadFile
from minio.error import MinioException
from PIL import Image

from app.core.config import settings
from app.core.email import Mail, Mailer
from app.core.exceptions import (
    BadRequestError,
    EmailDeliveryError,
    PayloadTooLargeError,
    StorageError,
)
from app.core.storage import Storage, image_url
from app.shared.images import read_image, replace_image, to_webp
from tests.fakes import FakeStorage


def make_image(fmt: str = "PNG", size: tuple[int, int] = (1200, 600), mode: str = "RGB") -> bytes:
    output = io.BytesIO()
    color = (0, 128, 128, 100) if mode == "RGBA" else "teal"  # semi-transparent for RGBA
    Image.new(mode, size, color).save(output, format=fmt)
    return output.getvalue()


def upload(data: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename="picture")


# --- to_webp / read_image ---


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "GIF"])
def test_to_webp_converts_and_shrinks(fmt: str) -> None:
    result = Image.open(io.BytesIO(to_webp(make_image(fmt), max_size=512)))

    assert result.format == "WEBP"
    assert max(result.size) == 512
    assert result.size == (512, 256)  # aspect ratio kept


def test_to_webp_keeps_transparency() -> None:
    result = Image.open(io.BytesIO(to_webp(make_image("PNG", mode="RGBA"), max_size=64)))
    assert result.mode == "RGBA"


def test_to_webp_rejects_unsupported_format() -> None:
    with pytest.raises(BadRequestError, match="JPEG, PNG, WebP or GIF"):
        to_webp(make_image("BMP"), max_size=64)


def test_to_webp_rejects_non_images() -> None:
    with pytest.raises(BadRequestError, match="not a valid image"):
        to_webp(b"definitely not an image", max_size=64)


def test_to_webp_rejects_truncated_images() -> None:
    with pytest.raises(BadRequestError, match="not a valid image"):
        to_webp(make_image("PNG")[:200], max_size=64)


async def test_read_image_returns_webp() -> None:
    data = await read_image(upload(make_image("JPEG")))
    assert Image.open(io.BytesIO(data)).format == "WEBP"


async def test_read_image_rejects_large_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "image_max_bytes", 2 * 1024 * 1024)
    with pytest.raises(PayloadTooLargeError, match="at most 2 MB"):
        await read_image(upload(b"x" * (2 * 1024 * 1024 + 1)))


async def test_read_image_rejects_empty_files() -> None:
    with pytest.raises(BadRequestError, match="empty"):
        await read_image(upload(b""))


async def test_replace_image_stores_new_key_and_deletes_old() -> None:
    storage = FakeStorage()
    storage.files["users/1/old.webp"] = (b"old", "image/webp")

    key = await replace_image(storage, folder="users/1", image=b"new", old_key="users/1/old.webp")

    assert key.startswith("users/1/") and key.endswith(".webp")
    assert storage.files == {key: (b"new", "image/webp")}


async def test_replace_image_without_old_key() -> None:
    storage = FakeStorage()
    key = await replace_image(storage, folder="contacts/1", image=b"img", old_key=None)
    assert list(storage.files) == [key]


# --- Storage ---


@pytest.fixture
def storage() -> Storage:
    storage = Storage(settings)
    storage._client = MagicMock()
    return storage


async def test_put_creates_bucket_once(storage: Storage) -> None:
    client: Any = storage._client
    client.bucket_exists.return_value = False

    await storage.put("a.webp", b"123", "image/webp")
    await storage.put("b.webp", b"456", "image/webp")

    client.make_bucket.assert_called_once_with(settings.s3_bucket)
    assert client.put_object.call_count == 2
    bucket, key, _, length = client.put_object.call_args.args
    assert (bucket, key, length) == (settings.s3_bucket, "b.webp", 3)
    assert client.put_object.call_args.kwargs == {"content_type": "image/webp"}


async def test_put_skips_existing_bucket(storage: Storage) -> None:
    client: Any = storage._client
    client.bucket_exists.return_value = True

    await storage.put("a.webp", b"1", "image/webp")

    client.make_bucket.assert_not_called()


async def test_put_failure_raises_storage_error(storage: Storage) -> None:
    client: Any = storage._client
    client.bucket_exists.side_effect = OSError("connection refused")

    with pytest.raises(StorageError, match="MinIO"):
        await storage.put("a.webp", b"1", "image/webp")


async def test_delete_removes_object(storage: Storage) -> None:
    await storage.delete("a.webp")
    storage._client.remove_object.assert_called_once_with(settings.s3_bucket, "a.webp")


async def test_delete_failure_is_only_logged(storage: Storage) -> None:
    client: Any = storage._client
    client.remove_object.side_effect = MinioException("boom")

    await storage.delete("a.webp")  # does not raise


def test_url_is_presigned_for_the_public_host_and_stable() -> None:
    storage = Storage(settings)

    url = storage.url("contacts/1/a.webp")

    assert url.startswith(f"{settings.s3_public_url}/{settings.s3_bucket}/contacts/1/a.webp?")
    assert "X-Amz-Signature=" in url
    assert storage.url("contacts/1/a.webp") == url  # same hour, same URL (browser cache)


def test_image_url_handles_missing_keys() -> None:
    assert image_url(None) is None
    assert image_url("x.webp") is not None


# --- Mailer ---


def test_build_message() -> None:
    mailer = Mailer(settings)

    message = mailer.build(
        Mail(
            to="Jane <jane@acme.com>",
            subject="Hi",
            text="Plain",
            html="<p>Rich</p>",
            reply_to="me@example.com",
            from_name="Ada via Auto CRM",
        )
    )

    assert message["From"] == f"Ada via Auto CRM <{settings.mail_from_email}>"
    assert message["To"] == "Jane <jane@acme.com>"
    assert message["Reply-To"] == "me@example.com"
    assert message.is_multipart()


def test_build_plain_message_uses_default_sender() -> None:
    message = Mailer(settings).build(Mail(to="a@b.com", subject="Hi", text="Plain"))

    assert message["From"] == f"{settings.mail_from_name} <{settings.mail_from_email}>"
    assert message["Reply-To"] is None
    assert not message.is_multipart()


async def test_send_uses_smtp_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    send = AsyncMock()
    monkeypatch.setattr(aiosmtplib, "send", send)

    await Mailer(settings).send(Mail(to="a@b.com", subject="Hi", text="Plain"))

    kwargs = send.await_args.kwargs
    assert kwargs["hostname"] == settings.smtp_host
    assert kwargs["port"] == settings.smtp_port
    assert kwargs["username"] is None  # empty settings mean "no login"
    assert kwargs["local_hostname"] == settings.mail_from_email.rpartition("@")[2]


async def test_send_failure_raises_email_delivery_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aiosmtplib, "send", AsyncMock(side_effect=ConnectionRefusedError()))

    with pytest.raises(EmailDeliveryError, match="Mailpit"):
        await Mailer(settings).send(Mail(to="a@b.com", subject="Hi", text="Plain"))
