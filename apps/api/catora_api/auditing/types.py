from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

type AttributeValue = (
    Mapping[str, object] | Sequence[object] | str | int | float | bool | None
)
type Severity = Literal["critical", "high", "medium", "low", "informational"]
type ScoreDimension = Literal[
    "completeness",
    "consistency",
    "variant_quality",
    "market_consistency",
    "discoverability_readiness",
]
type EvaluationOutcome = Literal["passed", "failed", "not_evaluated"]


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    source_record_id: uuid.UUID
    field_path: str
    excerpt: str | None = None
    checksum: str | None = None


@dataclass(frozen=True, slots=True)
class AttributeSnapshot:
    key: str
    value: AttributeValue
    value_type: str
    value_state: str = "present"
    unit: str | None = None
    locale: str | None = None
    evidence: tuple[EvidenceSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class VariantAuditSnapshot:
    variant_id: uuid.UUID
    attributes: Mapping[str, AttributeSnapshot] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProductAuditSnapshot:
    product_id: uuid.UUID
    category_key: str
    attributes: Mapping[str, AttributeSnapshot] = field(default_factory=dict)
    variants: tuple[VariantAuditSnapshot, ...] = ()
    source_coverage_basis_points: int = 10000

    def __post_init__(self) -> None:
        if not 0 <= self.source_coverage_basis_points <= 10000:
            raise ValueError("source_coverage_basis_points must be between 0 and 10000")


@dataclass(frozen=True, slots=True)
class FindingCandidate:
    fingerprint: str
    rule_version_id: uuid.UUID
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    severity: Severity
    title: str
    explanation: str
    field_key: str
    affected_value: AttributeValue
    evidence: tuple[EvidenceSnapshot, ...]
    business_impact: str
    remediation_type: str
    failure_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    rule_version_id: uuid.UUID
    rule_key: str
    product_id: uuid.UUID
    variant_id: uuid.UUID | None
    field_key: str
    check_key: str
    dimension: ScoreDimension
    severity: Severity
    weight: int
    outcome: EvaluationOutcome
    coverage_basis_points: int
    finding: FindingCandidate | None = None
