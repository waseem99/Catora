from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.workflow import Recommendation, RecommendationField
from catora_api.enrichment.types import EnrichmentRequest, EnrichmentResult


class RecommendationPersistenceError(ValueError):
    pass


class RecommendationIdentityMismatchError(RecommendationPersistenceError):
    pass


@dataclass(frozen=True, slots=True)
class PersistedRecommendation:
    recommendation: Recommendation
    fields: tuple[RecommendationField, ...]


class RecommendationPersistenceService:
    async def persist(
        self,
        session: AsyncSession,
        *,
        request: EnrichmentRequest,
        result: EnrichmentResult,
        audit_finding_id: uuid.UUID | None = None,
    ) -> PersistedRecommendation:
        _validate_identity(request, result)
        recommendation = Recommendation(
            workspace_id=request.workspace_id,
            product_id=request.product_id,
            variant_id=request.variant_id,
            audit_finding_id=audit_finding_id,
            status="draft",
            task_type=request.task_type,
            model_provider=result.provider_name,
            model_name=result.model_name,
            prompt_version=result.prompt_version,
            cost_microunits=result.cost_microunits,
            source_snapshot_hash=source_snapshot_hash(request),
            execution_metadata={
                "request_id": str(result.request_id),
                "prompt_fingerprint": result.prompt_fingerprint,
                "attempt_count": result.attempt_count,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )
        session.add(recommendation)
        await session.flush()
        if recommendation.id is None:
            raise RecommendationPersistenceError(
                "recommendation identifier was not assigned during persistence"
            )

        fields = tuple(
            RecommendationField(
                workspace_id=request.workspace_id,
                recommendation_id=recommendation.id,
                field_key=candidate.field_key,
                original_value=request.original_values.get(candidate.field_key),
                proposed_value=candidate.proposed_value,
                edited_value=None,
                evidence=[item.model_dump(mode="json") for item in candidate.evidence],
                confidence=candidate.confidence,
                requires_verification=candidate.requires_verification,
                proposal_metadata={
                    "explanation": candidate.explanation,
                    "claim_type": candidate.claim_type,
                    "inferred": candidate.inferred,
                    "evidence_conflict": candidate.evidence_conflict,
                },
            )
            for candidate in sorted(result.candidates, key=lambda item: item.field_key)
        )
        for field in fields:
            session.add(field)
        await session.flush()
        return PersistedRecommendation(
            recommendation=recommendation,
            fields=fields,
        )


def source_snapshot_hash(request: EnrichmentRequest) -> str:
    payload = {
        "workspace_id": str(request.workspace_id),
        "product_id": str(request.product_id),
        "variant_id": str(request.variant_id) if request.variant_id is not None else None,
        "task_type": request.task_type,
        "allowed_fields": sorted(request.allowed_fields),
        "original_values": request.original_values,
        "brand_controls": request.brand_controls.model_dump(mode="json"),
        "sources": [
            {
                "source_record_id": str(item.source_record_id),
                "field_path": item.field_path,
                "content_hash": hashlib.sha256(item.content.encode("utf-8")).hexdigest(),
                "checksum": item.checksum,
                "kind": item.kind,
            }
            for item in sorted(
                request.sources,
                key=lambda source: (str(source.source_record_id), source.field_path),
            )
        ],
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _validate_identity(
    request: EnrichmentRequest,
    result: EnrichmentResult,
) -> None:
    mismatches: list[str] = []
    for field_name in (
        "workspace_id",
        "product_id",
        "variant_id",
        "task_type",
    ):
        if getattr(request, field_name) != getattr(result, field_name):
            mismatches.append(field_name)
    if mismatches:
        raise RecommendationIdentityMismatchError(
            "enrichment result identity does not match request: "
            + ", ".join(sorted(mismatches))
        )
