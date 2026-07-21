from __future__ import annotations

from dataclasses import dataclass

from catora_api.auditing.types import RuleEvaluation, ScoreDimension

_ALL_DIMENSIONS: tuple[ScoreDimension, ...] = (
    "completeness",
    "consistency",
    "variant_quality",
    "market_consistency",
    "discoverability_readiness",
)


@dataclass(frozen=True, slots=True)
class ScoreContribution:
    rule_key: str
    rule_version_id: str
    product_id: str
    variant_id: str | None
    check_key: str
    dimension: ScoreDimension
    weight: int
    outcome: str
    coverage_basis_points: int


@dataclass(frozen=True, slots=True)
class DimensionScore:
    dimension: ScoreDimension | str
    score_basis_points: int
    confidence_basis_points: int
    eligible_weight: int
    evaluated_weight: int
    passed_weight: int
    contributions: tuple[ScoreContribution, ...]

    @property
    def score(self) -> float:
        return self.score_basis_points / 100

    @property
    def confidence(self) -> float:
        return self.confidence_basis_points / 100


@dataclass(frozen=True, slots=True)
class CatalogHealthScore:
    overall: DimensionScore
    dimensions: dict[ScoreDimension, DimensionScore]


def calculate_health_score(
    evaluations: tuple[RuleEvaluation, ...],
) -> CatalogHealthScore:
    dimensions = {
        dimension: _score_dimension(
            dimension,
            tuple(item for item in evaluations if item.dimension == dimension),
        )
        for dimension in _ALL_DIMENSIONS
    }
    overall = _score_dimension("overall", evaluations)
    return CatalogHealthScore(overall=overall, dimensions=dimensions)


def _score_dimension(
    dimension: ScoreDimension | str,
    evaluations: tuple[RuleEvaluation, ...],
) -> DimensionScore:
    eligible_weight = sum(item.weight for item in evaluations)
    evaluated = tuple(item for item in evaluations if item.outcome != "not_evaluated")
    evaluated_weight = sum(item.weight for item in evaluated)
    passed_weight = sum(item.weight for item in evaluated if item.outcome == "passed")
    score_basis_points = (
        (passed_weight * 10000 + evaluated_weight // 2) // evaluated_weight
        if evaluated_weight
        else 0
    )
    confidence_basis_points = (
        sum(item.weight * item.coverage_basis_points for item in evaluated)
        // eligible_weight
        if eligible_weight
        else 0
    )
    contributions = tuple(
        ScoreContribution(
            rule_key=item.rule_key,
            rule_version_id=str(item.rule_version_id),
            product_id=str(item.product_id),
            variant_id=str(item.variant_id) if item.variant_id else None,
            check_key=item.check_key,
            dimension=item.dimension,
            weight=item.weight,
            outcome=item.outcome,
            coverage_basis_points=item.coverage_basis_points,
        )
        for item in evaluations
    )
    return DimensionScore(
        dimension=dimension,
        score_basis_points=score_basis_points,
        confidence_basis_points=confidence_basis_points,
        eligible_weight=eligible_weight,
        evaluated_weight=evaluated_weight,
        passed_weight=passed_weight,
        contributions=contributions,
    )
