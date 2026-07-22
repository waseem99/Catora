from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.audit import AuditFinding
from catora_api.db.models.catalog import (
    EvidenceReference,
    Product,
    ProductVariant,
    SourceRecord,
)
from catora_api.enrichment.errors import EnrichmentGatewayError
from catora_api.enrichment.gateway import EnrichmentGateway
from catora_api.enrichment.persistence import (
    PersistedRecommendation,
    RecommendationPersistenceService,
)
from catora_api.enrichment.provider import ProviderAdapter
from catora_api.enrichment.types import EnrichmentRequest


class RecommendationTargetError(ValueError):
    pass


class RecommendationProviderError(RuntimeError):
    pass


class RecommendationGenerationService:
    def __init__(self) -> None:
        self._persistence = RecommendationPersistenceService()

    async def generate(
        self,
        session: AsyncSession,
        *,
        request: EnrichmentRequest,
        provider: ProviderAdapter,
        budget_microunits: int,
        concurrency_limit: int,
        max_attempts: int,
        max_output_tokens: int,
        audit_finding_id: uuid.UUID | None = None,
    ) -> PersistedRecommendation:
        await _validate_target(
            session,
            request=request,
            audit_finding_id=audit_finding_id,
        )
        gateway = EnrichmentGateway(
            provider,
            budget_microunits=budget_microunits,
            concurrency_limit=concurrency_limit,
            max_attempts=max_attempts,
            max_output_tokens=max_output_tokens,
        )
        try:
            result = await gateway.run(request)
        except Exception as exc:
            if isinstance(exc, EnrichmentGatewayError):
                raise
            raise RecommendationProviderError("Enrichment provider call failed") from exc
        return await self._persistence.persist(
            session,
            request=request,
            result=result,
            audit_finding_id=audit_finding_id,
        )


async def _validate_target(
    session: AsyncSession,
    *,
    request: EnrichmentRequest,
    audit_finding_id: uuid.UUID | None,
) -> None:
    product_id = await session.scalar(
        select(Product.id).where(
            Product.id == request.product_id,
            Product.workspace_id == request.workspace_id,
            Product.deleted_at.is_(None),
        )
    )
    if product_id is None:
        raise RecommendationTargetError("Recommendation target not found")

    if request.variant_id is not None:
        variant_product_id = await session.scalar(
            select(ProductVariant.product_id).where(
                ProductVariant.id == request.variant_id,
                ProductVariant.workspace_id == request.workspace_id,
                ProductVariant.deleted_at.is_(None),
            )
        )
        if variant_product_id != request.product_id:
            raise RecommendationTargetError("Recommendation target not found")

    source_ids = {source.source_record_id for source in request.sources}
    workspace_source_ids = set(
        (
            await session.scalars(
                select(SourceRecord.id).where(
                    SourceRecord.workspace_id == request.workspace_id,
                    SourceRecord.id.in_(source_ids),
                )
            )
        ).all()
    )
    if workspace_source_ids != source_ids:
        raise RecommendationTargetError("Recommendation evidence not found")

    variant_filter = (
        EvidenceReference.variant_id.is_(None)
        if request.variant_id is None
        else or_(
            EvidenceReference.variant_id.is_(None),
            EvidenceReference.variant_id == request.variant_id,
        )
    )
    product_evidence_ids = set(
        (
            await session.scalars(
                select(EvidenceReference.source_record_id).where(
                    EvidenceReference.workspace_id == request.workspace_id,
                    EvidenceReference.product_id == request.product_id,
                    EvidenceReference.source_record_id.in_(source_ids),
                    variant_filter,
                )
            )
        ).all()
    )
    if product_evidence_ids != source_ids:
        raise RecommendationTargetError("Recommendation evidence not found")

    if audit_finding_id is None:
        return
    finding_product_id = await session.scalar(
        select(AuditFinding.product_id).where(
            AuditFinding.id == audit_finding_id,
            AuditFinding.workspace_id == request.workspace_id,
        )
    )
    if finding_product_id != request.product_id:
        raise RecommendationTargetError("Recommendation target not found")
    finding_variant_id = await session.scalar(
        select(AuditFinding.variant_id).where(
            AuditFinding.id == audit_finding_id,
            AuditFinding.workspace_id == request.workspace_id,
        )
    )
    if finding_variant_id != request.variant_id:
        raise RecommendationTargetError("Recommendation target not found")
