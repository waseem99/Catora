from __future__ import annotations

import uuid
from dataclasses import fields
from typing import cast

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.catalog import CatalogSource, IngestionJob, SourceRecord
from catora_api.normalization.restaurant_bridge import (
    RestaurantBridgeNormalizationPipeline,
    RestaurantBridgeNormalizationSummary,
    _Counters,
)
from catora_api.restaurant.projection import stable_canonical_key
from catora_api.schemas.restaurant_bridge import RestaurantBridgeBrand


class RestaurantBridgeRuntimePipeline(RestaurantBridgeNormalizationPipeline):
    """Runs the restaurant bridge normalizer without relying on a slots __dict__."""

    async def normalize_job(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        job: IngestionJob,
    ) -> RestaurantBridgeNormalizationSummary:
        workspace_id = cast(uuid.UUID, source.workspace_id)
        if workspace_id != job.workspace_id:
            raise ValueError("Source and job belong to different workspaces")
        if source.id != job.catalog_source_id:
            raise ValueError("Job does not belong to source")
        if source.config.get("profile") != "restaurant/v1":
            raise ValueError("Catalog source is not a restaurant bridge profile")
        records = (
            await session.scalars(
                select(SourceRecord)
                .where(
                    SourceRecord.workspace_id == workspace_id,
                    SourceRecord.catalog_source_id == source.id,
                    SourceRecord.last_seen_job_id == job.id,
                    SourceRecord.record_type == "restaurant_brand",
                )
                .order_by(SourceRecord.snapshot_at, SourceRecord.id)
            )
        ).all()
        counters = _Counters()
        active_brand_keys: set[str] = set()
        for record in records:
            try:
                payload = RestaurantBridgeBrand.model_validate(record.payload)
            except ValidationError:
                counters.records_rejected += 1
                continue
            brand_key = stable_canonical_key("restaurant-brand", str(source.id), payload.id)
            active_brand_keys.add(brand_key)
            await self._persist_brand(
                session,
                source=source,
                record=record,
                payload=payload,
                brand_key=brand_key,
                counters=counters,
            )
        await self._retire_missing_brands(
            session,
            source=source,
            active_brand_keys=active_brand_keys,
        )
        await session.commit()
        values = {
            field.name: cast(int, getattr(counters, field.name))
            for field in fields(counters)
        }
        return RestaurantBridgeNormalizationSummary(**values)
