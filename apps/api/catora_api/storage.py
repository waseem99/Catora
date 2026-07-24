from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.exceptions import ClientError

from catora_api.config import Settings


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str


class ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self) -> Any:
        return boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
        )

    async def ensure_bucket(self) -> None:
        def ensure() -> None:
            client = self._client()
            try:
                client.head_bucket(Bucket=self.settings.s3_bucket)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code not in {"404", "NoSuchBucket", "NotFound"}:
                    raise
                client.create_bucket(Bucket=self.settings.s3_bucket)

        await asyncio.to_thread(ensure)

    async def put_bytes(self, key: str, content: bytes, *, content_type: str) -> StoredObject:
        await self.ensure_bucket()

        def upload() -> None:
            self._client().put_object(
                Bucket=self.settings.s3_bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )

        await asyncio.to_thread(upload)
        return StoredObject(key=key, size_bytes=len(content), content_type=content_type)

    async def get_bytes(self, key: str) -> bytes:
        def download() -> bytes:
            response = self._client().get_object(Bucket=self.settings.s3_bucket, Key=key)
            body = response["Body"].read()
            if not isinstance(body, bytes):
                raise TypeError("Object storage returned non-byte content")
            return body

        return await asyncio.to_thread(download)

    async def delete(self, key: str) -> None:
        if not key:
            return

        def remove() -> None:
            self._client().delete_object(Bucket=self.settings.s3_bucket, Key=key)

        await asyncio.to_thread(remove)

    async def delete_prefix(self, prefix: str) -> int:
        normalized = prefix.strip("/")
        if not normalized:
            raise ValueError("Object storage deletion prefix cannot be empty")
        normalized = f"{normalized}/"

        def remove() -> int:
            client = self._client()
            continuation: str | None = None
            deleted = 0
            while True:
                request: dict[str, object] = {
                    "Bucket": self.settings.s3_bucket,
                    "Prefix": normalized,
                }
                if continuation is not None:
                    request["ContinuationToken"] = continuation
                response = client.list_objects_v2(**request)
                contents = response.get("Contents", [])
                objects = [
                    {"Key": item["Key"]}
                    for item in contents
                    if isinstance(item, dict)
                    and isinstance(item.get("Key"), str)
                    and item["Key"]
                ]
                if objects:
                    client.delete_objects(
                        Bucket=self.settings.s3_bucket,
                        Delete={"Objects": objects, "Quiet": True},
                    )
                    deleted += len(objects)
                if not response.get("IsTruncated"):
                    return deleted
                token = response.get("NextContinuationToken")
                if not isinstance(token, str) or not token:
                    raise RuntimeError(
                        "Object storage pagination omitted the continuation token"
                    )
                continuation = token

        return await asyncio.to_thread(remove)
