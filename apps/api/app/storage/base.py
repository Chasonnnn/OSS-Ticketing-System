from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoredBlob:
    storage_key: str
    size_bytes: int


class BlobStoreError(RuntimeError):
    pass


class BlobStore:
    def put_bytes(
        self, *, key: str, data: bytes, content_type: str | None
    ) -> StoredBlob:  # pragma: no cover
        raise NotImplementedError

    def get_bytes(self, *, key: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def get_download_url(
        self,
        *,
        key: str,
        expires_in_seconds: int,
        filename: str | None,
        content_type: str | None,
    ) -> str | None:
        _ = key, expires_in_seconds, filename, content_type
        return None
