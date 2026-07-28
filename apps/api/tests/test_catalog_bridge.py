from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from catora_api.catalog_bridge.security import CatalogBridgeAuthenticator
from catora_api.config import Settings
from catora_api.connectors.catalog_bridge import CatalogBridgeConnector
from catora_api.db.models.catalog import CatalogSource
from catora_api.schemas.catalog_bridge import (
    CATALOG_BRIDGE_PROTOCOL_VERSION,
    CatalogBridgeProduct,
)


def _settings() -> Settings:
    key = base64.urlsafe_b64encode(b"b" * 32).decode()
    return Settings(
        catalog_bridge_enabled=True,
        catalog_bridge_credential_encryption_key=key,
    )


def _request(
    *,
    method: str,
    path: str,
    body: bytes,
    token: str,
    timestamp: int | None = None,
) -> Request:
    timestamp_text = str(timestamp or int(datetime.now(UTC).timestamp()))
    content_hash = hashlib.sha256(body).hexdigest()
    idempotency_key = "snapshot:batch:00000000"
    canonical = "\n".join(
        (method, path, timestamp_text, content_hash, idempotency_key)
    )
    signature = hmac.new(token.encode(), canonical.encode(), hashlib.sha256).digest()
    signature_text = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    headers = [
        (b"x-catora-timestamp", timestamp_text.encode()),
        (b"x-catora-content-sha256", content_hash.encode()),
        (b"x-catora-idempotency-key", idempotency_key.encode()),
        (b"x-catora-signature", signature_text.encode()),
    ]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "server": ("api.example.com", 443),
        }
    )


@pytest.mark.asyncio
async def test_catalog_bridge_request_authentication_fails_closed() -> None:
    settings = _settings()
    source = CatalogSource(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="Custom catalog",
        source_type="bridge",
        status="ready",
        config={},
    )
    authenticator = CatalogBridgeAuthenticator(settings)
    credential = authenticator.rotate(source)
    body = b'{"records":[]}'
    path = f"/api/v1/catalog-bridge/sources/{source.id}/snapshots"
    request = _request(
        method="POST",
        path=path,
        body=body,
        token=credential.token,
    )

    await authenticator.authenticate(request, source=source, body=body)

    tampered = _request(
        method="POST",
        path=path,
        body=body,
        token="wrong-token",
    )
    with pytest.raises(Exception, match="signature is invalid"):
        await authenticator.authenticate(tampered, source=source, body=body)


@pytest.mark.parametrize(
    "attributes",
    [
        {"customer_token": "secret"},
        {"order": {"id": "not-catalog-data"}},
        {"payment.address": "not-allowed"},
    ],
)
def test_catalog_bridge_contract_rejects_sensitive_fields(
    attributes: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        CatalogBridgeProduct.model_validate(
            {
                "id": "product-1",
                "title": "Chair",
                "attributes": attributes,
            }
        )


class _MemoryStorage:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def get_bytes(self, key: str) -> bytes:
        assert key == "bridge/batch.json"
        return self.content


@pytest.mark.asyncio
async def test_catalog_bridge_connector_emits_deterministic_product_records() -> None:
    payload = {
        "protocolVersion": CATALOG_BRIDGE_PROTOCOL_VERSION,
        "snapshotId": "eea3b074-4d5a-4d22-82fe-e6f5dedf55c8",
        "sequence": 0,
        "records": [
            {
                "id": "product-1",
                "title": "Oak table",
                "attributes": {"material": "Oak"},
                "variants": [{"id": "variant-1", "sku": "OAK-1"}],
            }
        ],
    }
    content = json.dumps(payload, separators=(",", ":")).encode()
    connector = CatalogBridgeConnector(
        config={
            "bridge_snapshot": {
                "protocol_version": CATALOG_BRIDGE_PROTOCOL_VERSION,
                "status": "complete",
                "batches": [
                    {
                        "sequence": 0,
                        "object_key": "bridge/batch.json",
                        "checksum": hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        },
        storage=_MemoryStorage(content),  # type: ignore[arg-type]
    )

    pages = [page async for page in connector.pages()]

    assert len(pages) == 1
    assert pages[0].records[0].external_id == "product-1"
    assert pages[0].records[0].payload["title"] == "Oak table"
    assert pages[0].next_checkpoint == {"batch_sequence": 1}
