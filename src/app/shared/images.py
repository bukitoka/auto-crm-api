"""Image uploads: validate, normalize and store pictures (avatars, logos).

Every upload is decoded with Pillow, rotated according to its EXIF data, shrunk to
at most `IMAGE_MAX_SIZE_PX` and re-encoded as WebP. Re-encoding means we never
serve the original bytes (no hidden metadata, no disguised files), and every
stored image is small and in one format.
"""

import asyncio
import io
import uuid

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.core.exceptions import BadRequestError, PayloadTooLargeError
from app.core.storage import Storage

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
CONTENT_TYPE = "image/webp"


def to_webp(data: bytes, max_size: int) -> bytes:
    """Decode an uploaded image and return it as a resized WebP."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ALLOWED_FORMATS:
                raise BadRequestError("Upload a JPEG, PNG, WebP or GIF image")
            image.load()
            picture = ImageOps.exif_transpose(image)
            picture.thumbnail((max_size, max_size))
            mode = "RGBA" if picture.mode in ("RGBA", "LA", "P") else "RGB"
            output = io.BytesIO()
            picture.convert(mode).save(output, format="WEBP", quality=85)
            return output.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise BadRequestError("The file is not a valid image") from exc


async def read_image(upload: UploadFile) -> bytes:
    """Read an uploaded file (size-limited) and convert it to a WebP image."""
    data = await upload.read(settings.image_max_bytes + 1)
    if len(data) > settings.image_max_bytes:
        limit_mb = settings.image_max_bytes // (1024 * 1024)
        raise PayloadTooLargeError(f"Images can be at most {limit_mb} MB")
    if not data:
        raise BadRequestError("The uploaded file is empty")
    return await asyncio.to_thread(to_webp, data, settings.image_max_size_px)


async def replace_image(storage: Storage, *, folder: str, image: bytes, old_key: str | None) -> str:
    """Store `image` under a new key in `folder` and delete the previous file.

    A fresh key per upload means browsers never show a cached old picture.
    """
    key = f"{folder}/{uuid.uuid4().hex}.webp"
    await storage.put(key, image, CONTENT_TYPE)
    if old_key:
        await storage.delete(old_key)
    return key
