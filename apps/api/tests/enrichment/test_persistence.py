from __future__ import annotations

import uuid

import pytest

from catora_api.db.models.workflow import Recommendation, RecommendationField
from catora_api.enrichment.persistence import (
    RecommendationIdentityMismatchError,
    RecommendationPersistenceService,
    source_snapshot_hash,
)
from catora_api.enrichment.types import (
    BrandControls,
    EnrichmentRequest,
    EnrichmentResult,
    EvidenceReference,
    SourceDocument,
    ValidatedCandidate,
)


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_count = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1
        for value in self.added:
            if isinstance(value, Recommendation | RecommendationField) and value.id is None:
                value.id = uuid.uuid4()


def _request(*, content: str = "Width: 2100 mm") -> EnrichmentRequest:
    source_record_id = uuid.uuid4()
    return EnrichmentRequest(
        workspace_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        task_type="normalize_attributes",
        allowed_fields=("width_mm",),
        original_values={"width_mm": "210 cm"},
        sources=(
            SourceDocument(
                source_record_id=source_record_id,
                field_path="product.structured.width",
                content=content,
                kind="structured_field",
            ),
        ),
        brand_controls=BrandControls(tone="clear and factual"),
    )


def _result(request: EnrichmentRequest) -> EnrichmentResult:
    source = request.sources[0]
    return EnrichmentResult(
        request_id=uuid.uuid4(),
        workspace_id=request.workspace_id,
        product_id=request.product_id,
        variant_id=request.variant_id,
        task_type=request.task_type,
        provider_name="mock",
        model_name="mock-structured-v1",
        prompt_version="enrichment-gateway-v1",
        prompt_fingerprint="a" * 64,
        attempt_count=2,
        input_tokens=40,
        output_tokens=20,
        cost_microunits=200,
        candidates=(
            ValidatedCandidate(
                field_key="width_mm",
                proposed_value=2100,
                evidence=(
                    EvidenceReference(
                        source_record_id=source.source_record_id,
                        field_path=source.field_path,
                        excerpt=source.content,
                        kind=source.kind,
                    ),
                ),
                inferred=False,
                evidence_conflict=False,
                claim_type="fact",
                explanation="Normalized from direct structured evidence.",
                confidence="high",
                requires_verification=False,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_persistence_creates_append_only_recommendation_versions() -> None:
    request = _request()
    result = _result(request)
    session = RecordingSession()
    service = RecommendationPersistenceService()

    first = await service.persist(
        session,  # type: ignore[arg-type]
        request=request,
        result=result,
    )
    second = await service.persist(
        session,  # type: ignore[arg-type]
        request=request,
        result=result,
    )

    assert first.recommendation.id != second.recommendation.id
    assert first.recommendation.source_snapshot_hash == second.recommendation.source_snapshot_hash
    recommendations = [item for item in session.added if isinstance(item, Recommendation)]
    fields = [item for item in session.added if isinstance(item, RecommendationField)]
    assert len(recommendations) == 2
    assert len(fields) == 2
    assert session.flush_count == 4


@pytest.mark.asyncio
async def test_persistence_records_execution_and_proposal_metadata() -> None:
    request = _request()
    result = _result(request)
    persisted = await RecommendationPersistenceService().persist(
        RecordingSession(),  # type: ignore[arg-type]
        request=request,
        result=result,
    )

    recommendation = persisted.recommendation
    field = persisted.fields[0]
    assert recommendation.status == "draft"
    assert recommendation.model_provider == "mock"
    assert recommendation.prompt_version == "enrichment-gateway-v1"
    assert recommendation.cost_microunits == 200
    assert recommendation.execution_metadata == {
        "request_id": str(result.request_id),
        "prompt_fingerprint": "a" * 64,
        "attempt_count": 2,
        "input_tokens": 40,
        "output_tokens": 20,
    }
    assert field.original_value == "210 cm"
    assert field.proposed_value == 2100
    assert field.edited_value is None
    assert field.confidence == "high"
    assert field.requires_verification is False
    assert field.evidence[0]["source_record_id"] == str(request.sources[0].source_record_id)
    assert field.proposal_metadata == {
        "explanation": "Normalized from direct structured evidence.",
        "claim_type": "fact",
        "inferred": False,
        "evidence_conflict": False,
    }


@pytest.mark.asyncio
async def test_identity_mismatch_is_rejected_before_database_writes() -> None:
    request = _request()
    result = _result(request).model_copy(update={"product_id": uuid.uuid4()})
    session = RecordingSession()

    with pytest.raises(RecommendationIdentityMismatchError, match="product_id"):
        await RecommendationPersistenceService().persist(
            session,  # type: ignore[arg-type]
            request=request,
            result=result,
        )

    assert session.added == []
    assert session.flush_count == 0


def test_source_snapshot_hash_is_deterministic_and_content_sensitive() -> None:
    request = _request(content="Width: 2100 mm")
    same = request.model_copy()
    changed = request.model_copy(
        update={
            "sources": (
                request.sources[0].model_copy(update={"content": "Width: 2200 mm"}),
            )
        }
    )

    assert source_snapshot_hash(request) == source_snapshot_hash(same)
    assert source_snapshot_hash(request) != source_snapshot_hash(changed)
