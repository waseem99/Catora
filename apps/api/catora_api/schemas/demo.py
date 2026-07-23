from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DecisionName = Literal["approved", "rejected"]
DemoComponentState = Literal["ok", "warning", "error"]
DemoResetState = Literal["queued", "running", "completed", "failed"]


class DemoCatalogSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_count: int = Field(ge=0)
    variant_count: int = Field(ge=0)
    attribute_count: int = Field(ge=0)
    image_count: int = Field(ge=0)


class DemoAuditSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: uuid.UUID
    score_basis_points: int = Field(ge=0, le=10_000)
    confidence_basis_points: int = Field(ge=0, le=10_000)
    critical_count: int = Field(ge=0)
    high_count: int = Field(ge=0)
    medium_count: int = Field(ge=0)


class DemoGapSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_key: str = Field(min_length=1, max_length=150)
    label: str = Field(min_length=1, max_length=200)
    affected_products: int = Field(ge=0)


class DemoEvidenceView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str = Field(min_length=1, max_length=500)
    excerpt: str | None = Field(default=None, max_length=2_000)
    source_label: str = Field(min_length=1, max_length=200)


class DemoFindingView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: uuid.UUID
    product_id: uuid.UUID
    product_title: str = Field(min_length=1, max_length=500)
    severity: Literal["critical", "high", "medium", "low", "informational"]
    title: str = Field(min_length=1, max_length=300)
    explanation: str = Field(min_length=1)
    category_key: str = Field(min_length=1, max_length=150)
    field_key: str = Field(min_length=1, max_length=150)
    business_impact: str = Field(min_length=1, max_length=50)
    remediation_type: str = Field(min_length=1, max_length=80)
    evidence: list[dict[str, object]]


class DemoProductView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: uuid.UUID
    title: str = Field(min_length=1, max_length=500)
    canonical_key: str = Field(min_length=1, max_length=500)
    category_key: str = Field(min_length=1, max_length=150)
    source_evidence: list[DemoEvidenceView]


class DemoIntentView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: uuid.UUID
    name: str = Field(min_length=1, max_length=250)
    query: str = Field(min_length=1, max_length=2_000)
    confident_match_count: int = Field(ge=0)
    possible_match_count: int = Field(ge=0)
    non_match_count: int = Field(ge=0)
    insufficient_category_count: int = Field(ge=0)
    hero_product_before_status: str = Field(min_length=1, max_length=50)
    hero_product_after_status: str = Field(min_length=1, max_length=50)
    missing_fields: list[str]
    explanation: str = Field(min_length=1)


class DemoRecommendationFieldView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: uuid.UUID
    field_key: str = Field(min_length=1, max_length=150)
    label: str = Field(min_length=1, max_length=200)
    original_value: object | None
    proposed_value: object | None
    edited_value: object | None
    confidence: str = Field(min_length=1, max_length=20)
    requires_verification: bool
    evidence: list[dict[str, object]]
    decision: DecisionName | None
    decision_comment: str | None


class DemoRecommendationView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: uuid.UUID
    product_id: uuid.UUID
    product_title: str = Field(min_length=1, max_length=500)
    status: str = Field(min_length=1, max_length=30)
    source_snapshot_hash: str = Field(min_length=64, max_length=64)
    fields: list[DemoRecommendationFieldView]


class DemoChangeSetView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: uuid.UUID | None
    name: str | None
    status: str
    approved_field_count: int = Field(ge=0)
    rejected_field_count: int = Field(ge=0)
    export_ready: bool


class DemoOverviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: uuid.UUID
    workspace_name: str = Field(min_length=1, max_length=200)
    generated_at: datetime
    catalog: DemoCatalogSummary
    audit: DemoAuditSummary
    top_gaps: list[DemoGapSummary]
    hero_product: DemoProductView
    findings: list[DemoFindingView]
    intent: DemoIntentView
    recommendation: DemoRecommendationView
    change_set: DemoChangeSetView
    report_pptx_path: str
    operational_csv_path: str


class DemoComponentView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    state: DemoComponentState
    detail: str = Field(min_length=1, max_length=500)


class DemoVerifiedSnapshotView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    audit_run_id: uuid.UUID
    source_snapshot_hash: str = Field(min_length=64, max_length=64)
    verified_at: datetime
    product_count: int = Field(ge=0)
    variant_count: int = Field(ge=0)
    finding_count: int = Field(ge=0)
    recommendation_field_count: int = Field(ge=0)


class DemoPreflightResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: uuid.UUID
    generated_at: datetime
    ready: bool
    components: list[DemoComponentView]
    last_verified_snapshot: DemoVerifiedSnapshotView


class DemoResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=500)


class DemoResetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: uuid.UUID
    status: DemoResetState


class DemoResetStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: uuid.UUID
    status: DemoResetState
    detail: str = Field(min_length=1, max_length=500)


class DemoFieldDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_id: uuid.UUID
    decision: DecisionName
    edited_value: object | None = None
    verified: bool = False
    comment: str | None = Field(default=None, max_length=1_000)


class DemoRecommendationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_source_snapshot_hash: str = Field(min_length=64, max_length=64)
    decisions: list[DemoFieldDecisionRequest] = Field(min_length=1, max_length=100)


class DemoRecommendationDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    recommendation_id: uuid.UUID
    recommendation_status: str
    change_set_id: uuid.UUID | None
    approved_field_count: int = Field(ge=0)
    rejected_field_count: int = Field(ge=0)
    projected_intent_status: str = Field(min_length=1, max_length=50)
