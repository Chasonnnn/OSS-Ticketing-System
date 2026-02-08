from __future__ import annotations

from app.core.config import get_settings
from app.storage.base import BlobStore
from app.storage.local import LocalBlobStore
from app.storage.s3 import S3BlobStore, S3Config


def build_blob_store() -> BlobStore:
    settings = get_settings()
    if settings.BLOB_STORE == "local":
        return LocalBlobStore(settings.LOCAL_BLOB_DIR)
    if settings.BLOB_STORE == "s3":
        return S3BlobStore(
            S3Config(
                endpoint_url=settings.S3_ENDPOINT_URL,
                access_key_id=settings.S3_ACCESS_KEY_ID,
                secret_access_key=settings.S3_SECRET_ACCESS_KEY,
                bucket=settings.S3_BUCKET,
            )
        )
    raise ValueError(f"Unsupported BLOB_STORE: {settings.BLOB_STORE}")
