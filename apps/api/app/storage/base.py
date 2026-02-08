from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoredBlob:
    storage_key: str
    size_bytes: int


class BlobStoreError(RuntimeError):
    pass


class BlobStore:
    def put_bytes(self, *, key: str, data: bytes, content_type: str | None) -> StoredBlob:  # pragma: no cover
        raise NotImplementedError

    def get_bytes(self, *, key: str) -> bytes:  # pragma: no cover
        raise NotImplementedError

