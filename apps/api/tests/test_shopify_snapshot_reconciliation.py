from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from catora_api.connectors.base import ConnectorPage, ConnectorRecord
from catora_api.db.models.catalog import (
    CatalogSource,
    IngestionJob,
    Product,
    ProductVariant,
    SourceRecord,
)
from catora_api.ingestion.service import IngestionService
from catora_api.normalization.adapters import canonical_product_key
from catora_api.normalization.reconciliation import (
    is_shopify_full_reconciliation,
    retire_missing_shopify_products,
)


class ScalarResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class SnapshotSession:
    def __init__(self, scalar_batches: list[list[object]]) -> None:
        self.scalar_batches = scalar_batches
        self.added: list[object] = []
        self.flush_count = 0

    async def scalars(self, _statement: object) -> ScalarResult:
        return ScalarResult(self.scalar_batches.pop(0))

    def add_all(self, values: list[object]) -> None:
        self.added.extend(values)

    async def flush(self) -> None:
        self.flush_count += 1


def _source(workspace_id: uuid.UUID) -> CatalogSource:
    return CatalogSource(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        storefront_id=None,
        name="Prospect Shopify",
        source_type="shopify",
        status="active",
        config={},
        credential_ref="shopify-public-installation:test",
    )


def _job(
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    full: bool,
) -> IngestionJob:
    return IngestionJob(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        catalog_source_id=source_id,
        status="running",
        checkpoint={
            "shopify": {
                "reason": "scheduled_full_reconciliation" if full else "products/update",
                "full_reconciliation": full,
            }
        },
    )


@pytest.mark.asyncio
async def test_duplicate_source_record_is_marked_seen_in_current_snapshot() -> None:
    workspace_id = uuid.uuid4()
    source = _source(workspace_id)
    previous_job_id = uuid.uuid4()
    job = _job(workspace_id, source.id, full=True)
    existing = SourceRecord(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        catalog_source_id=source.id,
        ingestion_job_id=previous_job_id,
        last_seen_job_id=previous_job_id,
        external_id="gid://shopify/Product/1",
        record_type="product",
        payload={"product": {"id": "gid://shopify/Product/1"}},
        content_hash="a" * 64,
        source_updated_at=None,
    )
    page = ConnectorPage(
        records=(
            ConnectorRecord(
                external_id="gid://shopify/Product/1",
                record_type="product",
                payload={"product": {"id": "gid://shopify/Product/1"}},
                content_hash="a" * 64,
            ),
            ConnectorRecord(
                external_id="gid://shopify/Product/2",
                record_type="product",
                payload={"product": {"id": "gid://shopify/Product/2"}},
                content_hash="b" * 64,
            ),
        ),
        rejections=(),
        next_checkpoint=None,
    )
    session = SnapshotSession([[existing]])

    inserted = await IngestionService()._persist_page(
        cast(Any, session),
        source=source,
        job=job,
        page=page,
    )

    assert inserted == 1
    assert existing.ingestion_job_id == previous_job_id
    assert existing.last_seen_job_id == job.id
    assert len(session.added) == 1
    new_record = cast(SourceRecord, session.added[0])
    assert new_record.external_id == "gid://shopify/Product/2"
    assert new_record.ingestion_job_id == job.id
    assert new_record.last_seen_job_id == job.id
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_full_snapshot_retires_only_products_missing_from_shopify() -> None:
    workspace_id = uuid.uuid4()
    source = _source(workspace_id)
    job = _job(workspace_id, source.id, full=True)
    retained = Product(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        canonical_key=canonical_product_key(source.id, "gid://shopify/Product/1"),
        title="Retained",
        status="active",
    )
    stale = Product(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        canonical_key=canonical_product_key(source.id, "gid://shopify/Product/2"),
        title="Stale",
        status="active",
    )
    previously_deleted = Product(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        canonical_key=canonical_product_key(source.id, "gid://shopify/Product/3"),
        title="Already deleted",
        status="deleted",
        deleted_at=datetime(2026, 7, 26, tzinfo=UTC),
    )
    stale_variant = ProductVariant(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        product_id=stale.id,
        canonical_key=f"source:{source.id}:variant:2",
        sku="STALE-2",
        title="Stale variant",
        option_values={},
    )
    session = SnapshotSession(
        [[retained, stale, previously_deleted], [stale_variant]]
    )
    retired_at = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)

    summary = await retire_missing_shopify_products(
        cast(Any, session),
        source=source,
        job=job,
        desired_product_keys={retained.canonical_key},
        now=retired_at,
    )

    assert summary.products_retired == 1
    assert summary.variants_retired == 1
    assert retained.status == "active"
    assert retained.deleted_at is None
    assert stale.status == "deleted"
    assert stale.deleted_at == retired_at
    assert stale_variant.deleted_at == retired_at
    assert previously_deleted.deleted_at == datetime(2026, 7, 26, tzinfo=UTC)


def test_incremental_job_never_uses_missing_product_retirement() -> None:
    workspace_id = uuid.uuid4()
    source = _source(workspace_id)
    job = _job(workspace_id, source.id, full=False)

    assert is_shopify_full_reconciliation(job) is False
