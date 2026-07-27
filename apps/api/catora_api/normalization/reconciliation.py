from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.catalog import (
    CatalogSource,
    IngestionJob,
    Product,
    ProductVariant,
)


@dataclass(frozen=True, slots=True)
class SnapshotRetirementSummary:
    products_retired: int
    variants_retired: int


def is_shopify_full_reconciliation(job: IngestionJob) -> bool:
    shopify = job.checkpoint.get("shopify")
    return (
        isinstance(shopify, dict)
        and shopify.get("full_reconciliation") is True
    )


async def retire_missing_shopify_products(
    session: AsyncSession,
    *,
    source: CatalogSource,
    job: IngestionJob,
    desired_product_keys: set[str],
    now: datetime | None = None,
) -> SnapshotRetirementSummary:
    if source.source_type != "shopify" or not is_shopify_full_reconciliation(job):
        return SnapshotRetirementSummary(products_retired=0, variants_retired=0)
    workspace_id = cast(uuid.UUID, source.workspace_id)
    prefix = f"source:{source.id}:product:%"
    source_products = list(
        (
            await session.scalars(
                select(Product).where(
                    Product.workspace_id == workspace_id,
                    Product.canonical_key.like(prefix),
                )
            )
        ).all()
    )
    retired_at = now or datetime.now(UTC)
    stale_products = [
        product
        for product in source_products
        if product.canonical_key not in desired_product_keys
        and product.deleted_at is None
    ]
    for product in stale_products:
        product.status = "deleted"
        product.deleted_at = retired_at

    stale_ids = [product.id for product in stale_products]
    stale_variants: list[ProductVariant] = []
    if stale_ids:
        stale_variants = list(
            (
                await session.scalars(
                    select(ProductVariant).where(
                        ProductVariant.workspace_id == workspace_id,
                        ProductVariant.product_id.in_(stale_ids),
                        ProductVariant.deleted_at.is_(None),
                    )
                )
            ).all()
        )
        for variant in stale_variants:
            variant.deleted_at = retired_at

    return SnapshotRetirementSummary(
        products_retired=len(stale_products),
        variants_retired=len(stale_variants),
    )
