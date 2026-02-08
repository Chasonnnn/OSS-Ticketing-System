from __future__ import annotations

import os
from pathlib import Path

from app.storage.base import BlobStore, BlobStoreError, StoredBlob


class LocalBlobStore(BlobStore):
    def __init__(self, root_dir: str) -> None:
        self._root = Path(root_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: str) -> Path:
        key = key.lstrip("/")
        return self._root / key

    def put_bytes(self, *, key: str, data: bytes, content_type: str | None) -> StoredBlob:
        _ = content_type
        path = self._path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
            os.replace(tmp_path, path)
        except OSError as e:
            raise BlobStoreError(str(e)) from e
        return StoredBlob(storage_key=key, size_bytes=len(data))

    def get_bytes(self, *, key: str) -> bytes:
        path = self._path_for_key(key)
        try:
            return path.read_bytes()
        except OSError as e:
            raise BlobStoreError(str(e)) from e
