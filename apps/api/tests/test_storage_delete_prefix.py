from __future__ import annotations

from typing import Any

import pytest

from catora_api.config import Settings
from catora_api.storage import ObjectStorage


class FakeS3Client:
    def __init__(self) -> None:
        self.list_requests: list[dict[str, object]] = []
        self.delete_requests: list[dict[str, object]] = []

    def list_objects_v2(self, **request: object) -> dict[str, object]:
        self.list_requests.append(request)
        if "ContinuationToken" not in request:
            return {
                "Contents": [
                    {"Key": "workspaces/workspace-id/report-one.csv"},
                    {"Key": "workspaces/workspace-id/report-two.pptx"},
                ],
                "IsTruncated": True,
                "NextContinuationToken": "page-two",
            }
        return {
            "Contents": [
                {"Key": "workspaces/workspace-id/catalog/export.csv"},
            ],
            "IsTruncated": False,
        }

    def delete_objects(self, **request: object) -> None:
        self.delete_requests.append(request)


@pytest.mark.asyncio
async def test_delete_prefix_removes_every_paginated_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = ObjectStorage(Settings(_env_file=None))
    client = FakeS3Client()
    monkeypatch.setattr(storage, "_client", lambda: cast_client(client))

    deleted = await storage.delete_prefix("workspaces/workspace-id")

    assert deleted == 3
    assert storage.settings.s3_bucket == "catora"
    assert client.list_requests == [
        {"Bucket": "catora", "Prefix": "workspaces/workspace-id/"},
        {
            "Bucket": "catora",
            "Prefix": "workspaces/workspace-id/",
            "ContinuationToken": "page-two",
        },
    ]
    assert len(client.delete_requests) == 2


def cast_client(client: FakeS3Client) -> Any:
    return client


@pytest.mark.asyncio
async def test_delete_prefix_rejects_bucket_wide_deletion() -> None:
    storage = ObjectStorage(Settings(_env_file=None))
    with pytest.raises(ValueError, match="cannot be empty"):
        await storage.delete_prefix("/")
