"""Object storage for uploaded files (MinIO, or any S3-compatible service).

Files live in one private bucket. The database stores only the object *key*
(e.g. `contacts/<id>/<uuid>.webp`); API responses turn keys into short-lived
presigned URLs that the browser can load directly from MinIO.

The MinIO SDK is synchronous, so network calls run in a worker thread.
"""

import asyncio
import io
import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends
from minio import Minio
from minio.error import MinioException

from app.core.config import Settings, settings
from app.core.exceptions import StorageError

logger = logging.getLogger(__name__)

# Presigned URLs are signed at the start of the hour and stay valid for two hours.
# The same URL is therefore returned for a whole hour, so browsers can cache images.
_URL_LIFETIME = timedelta(hours=2)


class Storage:
    def __init__(self, config: Settings) -> None:
        self.bucket = config.s3_bucket
        # Used by the API itself (uploads, deletes).
        self._client = Minio(
            config.s3_endpoint,
            access_key=config.s3_access_key,
            secret_key=config.s3_secret_key,
            secure=config.s3_secure,
            region=config.s3_region,
        )
        # Only used to sign URLs for browsers. The signature includes the host, so it must
        # be signed for the public address. Setting `region` means signing needs no network.
        public = urlsplit(config.s3_public_url)
        self._signer = Minio(
            public.netloc,
            access_key=config.s3_access_key,
            secret_key=config.s3_secret_key,
            secure=public.scheme == "https",
            region=config.s3_region,
        )
        self._bucket_ready = False

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            await asyncio.to_thread(self._put_sync, key, data, content_type)
        except (MinioException, OSError) as exc:
            logger.exception("Uploading %s failed", key)
            raise StorageError() from exc

    async def delete(self, key: str) -> None:
        """Best effort: a leftover file is harmless, so failures are only logged."""
        try:
            await asyncio.to_thread(self._client.remove_object, self.bucket, key)
        except MinioException, OSError:
            logger.warning("Could not delete %s from object storage", key, exc_info=True)

    def url(self, key: str) -> str:
        signed_at = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        return self._signer.presigned_get_object(
            self.bucket, key, expires=_URL_LIFETIME, request_date=signed_at
        )

    def _put_sync(self, key: str, data: bytes, content_type: str) -> None:
        if not self._bucket_ready:
            if not self._client.bucket_exists(self.bucket):
                self._client.make_bucket(self.bucket)
            self._bucket_ready = True
        self._client.put_object(
            self.bucket, key, io.BytesIO(data), len(data), content_type=content_type
        )


@lru_cache
def get_storage() -> Storage:
    return Storage(settings)


StorageDep = Annotated[Storage, Depends(get_storage)]


def image_url(key: str | None) -> str | None:
    """Turn a stored object key into a URL the browser can load (None stays None)."""
    return get_storage().url(key) if key else None
