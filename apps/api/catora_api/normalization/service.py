from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.catalog import (
    CatalogSource,
    EvidenceReference,
    IngestionJob,
    Product,
    ProductAttribute,
    ProductImage,
    ProductVariant,
    SourceRecord,
)
from catora_api.normalization.adapters import normalize_source_records
from catora_api.normalization.types import (
    NormalizedAttribute,
    NormalizedImage,
    NormalizedProduct,
    NormalizedVariant,
)

TRANSFORMER_VERSION = "catalog-normalizer-v1"


@dataclass(frozen=True, slots=True)
class NormalizationSummary:
    products_created: int
    products_updated: int
    variants_created: int
    variants_updated: int
    attributes_created: int
    attributes_updated: int
    images_created: int
    rejected_records: int

    def as_dict(self) -> dict[str, int]:
        return {
            "products_created": self.products_created,
            "products_updated": self.products_updated,
            "variants_created": self.variants_created,
            "variants_updated": self.variants_updated,
            "attributes_created": self.attributes_created,
            "attributes_updated": self.attributes_updated,
            "images_created": self.images_created,
            "rejected_records": self.rejected_records,
        }


@dataclass(slots=True)
class _Counters:
    products_created: int = 0
    products_updated: int = 0
    variants_created: int = 0
    variants_updated: int = 0
    attributes_created: int = 0
    attributes_updated: int = 0
    images_created: int = 0

    def summary(self, *, rejected_records: int) -> NormalizationSummary:
        return NormalizationSummary(
            products_created=self.products_created,
            products_updated=self.products_updated,
            variants_created=self.variants_created,
            variants_updated=self.variants_updated,
            attributes_created=self.attributes_created,
            attributes_updated=self.attributes_updated,
            images_created=self.images_created,
            rejected_records=rejected_records,
        )


class CatalogNormalizationService:
    async def normalize_job(
        self,
        session: AsyncSession,
        *,
        source: CatalogSource,
        job: IngestionJob,
    ) -> NormalizationSummary:
        workspace_id = source.workspace_id
        if workspace_id != job.workspace_id:
            raise ValueError("Source and job belong to different workspaces")
        if source.id != job.catalog_source_id:
            raise ValueError("Job does not belong to source")

        records = (
            await session.scalars(
                select(SourceRecord)
                .where(
                    SourceRecord.workspace_id == workspace_id,
                    SourceRecord.catalog_source_id == source.id,
                    SourceRecord.ingestion_job_id == job.id,
                )
                .order_by(SourceRecord.snapshot_at, SourceRecord.id)
            )
        ).all()
        batch = normalize_source_records(source, records)
        counters = _Counters()
        for candidate in batch.products:
            await self._persist_product(
                session,
                workspace_id=workspace_id,
                candidate=candidate,
                counters=counters,
            )
        await session.commit()
        return counters.summary(rejected_records=len(batch.rejected_record_ids))

    async def _persist_product(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        candidate: NormalizedProduct,
        counters: _Counters,
    ) -> None:
        product = await session.scalar(
            select(Product).where(
                Product.workspace_id == workspace_id,
                Product.canonical_key == candidate.canonical_key,
            )
        )
        if product is None:
            product = Product(
                workspace_id=workspace_id,
                canonical_key=candidate.canonical_key,
                title=candidate.title,
                status="active",
            )
            session.add(product)
            await session.flush()
            counters.products_created += 1
        else:
            changed = (
                product.title != candidate.title
                or product.status != "active"
                or product.deleted_at is not None
            )
            product.title = candidate.title
            product.status = "active"
            product.deleted_at = None
            if changed:
                counters.products_updated += 1

        await self._ensure_evidence(
            session,
            workspace_id=workspace_id,
            source_record_id=candidate.source_record_id,
            product_id=product.id,
            field_path=candidate.title_field_path,
            excerpt=candidate.title,
        )
        product_attribute_ids = await self._sync_attributes(
            session,
            workspace_id=workspace_id,
            product=product,
            variant=None,
            candidates=candidate.attributes,
            counters=counters,
        )
        await self._sync_attribute_evidence(
            session,
            workspace_id=workspace_id,
            product=product,
            variant=None,
            candidates=candidate.attributes,
            attribute_ids=product_attribute_ids,
        )

        existing_variants = {
            variant.canonical_key: variant
            for variant in (
                await session.scalars(
                    select(ProductVariant).where(
                        ProductVariant.workspace_id == workspace_id,
                        ProductVariant.product_id == product.id,
                    )
                )
            ).all()
        }
        desired_variant_keys = {
            variant.canonical_key for variant in candidate.variants
        }
        variant_by_key: dict[str, ProductVariant] = {}
        for variant_candidate in candidate.variants:
            variant = existing_variants.get(variant_candidate.canonical_key)
            if variant is None:
                variant = ProductVariant(
                    workspace_id=workspace_id,
                    product_id=product.id,
                    canonical_key=variant_candidate.canonical_key,
                    sku=variant_candidate.sku,
                    title=variant_candidate.title,
                    option_values=dict(variant_candidate.option_values),
                )
                session.add(variant)
                await session.flush()
                counters.variants_created += 1
            else:
                option_values = dict(variant_candidate.option_values)
                changed = (
                    variant.sku != variant_candidate.sku
                    or variant.title != variant_candidate.title
                    or variant.option_values != option_values
                    or variant.deleted_at is not None
                )
                variant.sku = variant_candidate.sku
                variant.title = variant_candidate.title
                variant.option_values = option_values
                variant.deleted_at = None
                if changed:
                    counters.variants_updated += 1
            variant_by_key[variant_candidate.canonical_key] = variant
            await self._ensure_evidence(
                session,
                workspace_id=workspace_id,
                source_record_id=variant_candidate.source_record_id,
                product_id=product.id,
                variant_id=variant.id,
                field_path="variant.identity",
                excerpt=variant_candidate.source_id,
            )
            variant_attribute_ids = await self._sync_attributes(
                session,
                workspace_id=workspace_id,
                product=product,
                variant=variant,
                candidates=variant_candidate.attributes,
                counters=counters,
            )
            await self._sync_attribute_evidence(
                session,
                workspace_id=workspace_id,
                product=product,
                variant=variant,
                candidates=variant_candidate.attributes,
                attribute_ids=variant_attribute_ids,
            )

        retired_at = datetime.now(UTC)
        for canonical_key, variant in existing_variants.items():
            if canonical_key not in desired_variant_keys and variant.deleted_at is None:
                variant.deleted_at = retired_at
                counters.variants_updated += 1

        await self._sync_images(
            session,
            workspace_id=workspace_id,
            product=product,
            candidates=candidate.images,
            variants=variant_by_key,
            counters=counters,
        )

    async def _sync_attributes(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product: Product,
        variant: ProductVariant | None,
        candidates: tuple[NormalizedAttribute, ...],
        counters: _Counters,
    ) -> dict[str, uuid.UUID]:
        query = select(ProductAttribute).where(
            ProductAttribute.workspace_id == workspace_id,
            ProductAttribute.product_id == product.id,
        )
        if variant is None:
            query = query.where(ProductAttribute.variant_id.is_(None))
        else:
            query = query.where(ProductAttribute.variant_id == variant.id)
        existing = {
            attribute.key: attribute
            for attribute in (await session.scalars(query)).all()
        }
        desired_keys = {candidate.key for candidate in candidates}
        attribute_ids: dict[str, uuid.UUID] = {}
        for candidate in candidates:
            attribute = existing.get(candidate.key)
            if attribute is None:
                attribute = ProductAttribute(
                    workspace_id=workspace_id,
                    product_id=product.id,
                    variant_id=variant.id if variant else None,
                    key=candidate.key,
                    value=candidate.value,
                    value_type=candidate.value_type,
                    unit=candidate.unit,
                    locale=candidate.locale,
                    value_state="present",
                    transformer_version=TRANSFORMER_VERSION,
                    confidence=candidate.confidence,
                )
                session.add(attribute)
                await session.flush()
                counters.attributes_created += 1
            else:
                changed = (
                    attribute.value != candidate.value
                    or attribute.value_type != candidate.value_type
                    or attribute.unit != candidate.unit
                    or attribute.locale != candidate.locale
                    or attribute.value_state != "present"
                    or attribute.transformer_version != TRANSFORMER_VERSION
                    or attribute.confidence != candidate.confidence
                )
                attribute.value = candidate.value
                attribute.value_type = candidate.value_type
                attribute.unit = candidate.unit
                attribute.locale = candidate.locale
                attribute.value_state = "present"
                attribute.transformer_version = TRANSFORMER_VERSION
                attribute.confidence = candidate.confidence
                if changed:
                    counters.attributes_updated += 1
            attribute_ids[candidate.key] = attribute.id

        for key, attribute in existing.items():
            if (
                key not in desired_keys
                and attribute.transformer_version == TRANSFORMER_VERSION
                and attribute.value_state != "missing"
            ):
                attribute.value = None
                attribute.value_state = "missing"
                attribute.confidence = "high"
                counters.attributes_updated += 1
        return attribute_ids

    async def _sync_attribute_evidence(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product: Product,
        variant: ProductVariant | None,
        candidates: tuple[NormalizedAttribute, ...],
        attribute_ids: dict[str, uuid.UUID],
    ) -> None:
        for candidate in candidates:
            await self._ensure_evidence(
                session,
                workspace_id=workspace_id,
                source_record_id=candidate.source_record_id,
                product_id=product.id,
                variant_id=variant.id if variant else None,
                attribute_id=attribute_ids[candidate.key],
                field_path=candidate.field_path,
                excerpt=candidate.excerpt,
            )

    async def _sync_images(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        product: Product,
        candidates: tuple[NormalizedImage, ...],
        variants: dict[str, ProductVariant],
        counters: _Counters,
    ) -> None:
        existing = {
            (image.url, image.variant_id): image
            for image in (
                await session.scalars(
                    select(ProductImage).where(
                        ProductImage.workspace_id == workspace_id,
                        ProductImage.product_id == product.id,
                    )
                )
            ).all()
        }
        for candidate in candidates:
            variant = None
            if candidate.variant_key:
                variant = variants.get(candidate.variant_key)
                if variant is None:
                    raise ValueError("Image references an unknown normalized variant")
            key = (candidate.url, variant.id if variant else None)
            image = existing.get(key)
            if image is None:
                image = ProductImage(
                    workspace_id=workspace_id,
                    product_id=product.id,
                    variant_id=variant.id if variant else None,
                    url=candidate.url,
                    alt_text=candidate.alt_text,
                    position=candidate.position,
                    checksum=hashlib.sha256(
                        candidate.url.encode("utf-8")
                    ).hexdigest(),
                )
                session.add(image)
                counters.images_created += 1
            else:
                image.alt_text = candidate.alt_text
                image.position = candidate.position
            await self._ensure_evidence(
                session,
                workspace_id=workspace_id,
                source_record_id=candidate.source_record_id,
                product_id=product.id,
                variant_id=variant.id if variant else None,
                field_path=candidate.field_path,
                excerpt=candidate.url,
            )

    async def _ensure_evidence(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        source_record_id: uuid.UUID,
        product_id: uuid.UUID,
        field_path: str,
        excerpt: str | None,
        variant_id: uuid.UUID | None = None,
        attribute_id: uuid.UUID | None = None,
    ) -> None:
        query = select(EvidenceReference).where(
            EvidenceReference.workspace_id == workspace_id,
            EvidenceReference.source_record_id == source_record_id,
            EvidenceReference.product_id == product_id,
            EvidenceReference.field_path == field_path,
        )
        if variant_id is None:
            query = query.where(EvidenceReference.variant_id.is_(None))
        else:
            query = query.where(EvidenceReference.variant_id == variant_id)
        if attribute_id is None:
            query = query.where(EvidenceReference.attribute_id.is_(None))
        else:
            query = query.where(EvidenceReference.attribute_id == attribute_id)

        checksum_payload = json.dumps(
            {
                "workspace_id": str(workspace_id),
                "source_record_id": str(source_record_id),
                "product_id": str(product_id),
                "variant_id": str(variant_id) if variant_id else None,
                "attribute_id": str(attribute_id) if attribute_id else None,
                "field_path": field_path,
                "excerpt": excerpt,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        checksum = hashlib.sha256(checksum_payload.encode("utf-8")).hexdigest()
        evidence = await session.scalar(query)
        if evidence is None:
            session.add(
                EvidenceReference(
                    workspace_id=workspace_id,
                    source_record_id=source_record_id,
                    product_id=product_id,
                    variant_id=variant_id,
                    attribute_id=attribute_id,
                    field_path=field_path,
                    excerpt=excerpt,
                    checksum=checksum,
                )
            )
            return
        evidence.excerpt = excerpt
        evidence.checksum = checksum
