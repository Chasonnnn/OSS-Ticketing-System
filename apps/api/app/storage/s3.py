from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.storage.base import BlobStore, BlobStoreError, StoredBlob


@dataclass(frozen=True)
class S3Config:
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    bucket: str


class S3BlobStore(BlobStore):
    def __init__(self, config: S3Config) -> None:
        self._bucket = config.bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
        )

    def put_bytes(self, *, key: str, data: bytes, content_type: str | None) -> StoredBlob:
        extra_args: dict[str, str] = {}
        if content_type:
            extra_args["ContentType"] = content_type
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data, **extra_args)
        except (BotoCoreError, ClientError) as e:
            raise BlobStoreError(str(e)) from e
        return StoredBlob(storage_key=key, size_bytes=len(data))

    def get_bytes(self, *, key: str) -> bytes:
        try:
            res = self._client.get_object(Bucket=self._bucket, Key=key)
            body = res["Body"].read()
            if not isinstance(body, (bytes, bytearray)):
                raise BlobStoreError("S3 returned non-bytes body")
            return bytes(body)
        except (BotoCoreError, ClientError) as e:
            raise BlobStoreError(str(e)) from e

    def get_download_url(
        self,
        *,
        key: str,
        expires_in_seconds: int,
        filename: str | None,
        content_type: str | None,
    ) -> str | None:
        params: dict[str, str] = {"Bucket": self._bucket, "Key": key}
        if content_type:
            params["ResponseContentType"] = content_type
        if filename:
            params["ResponseContentDisposition"] = _build_attachment_disposition(filename)

        try:
            return self._client.generate_presigned_url(
                ClientMethod="get_object",
                Params=params,
                ExpiresIn=expires_in_seconds,
            )
        except (BotoCoreError, ClientError) as e:
            raise BlobStoreError(str(e)) from e


def _build_attachment_disposition(filename: str) -> str:
    ascii_name = (
        filename.encode("ascii", "ignore").decode("ascii").replace("\\", "_").replace('"', "'")
    )
    if not ascii_name:
        ascii_name = "attachment"
    utf8_name = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"
