from __future__ import annotations

from catora_api.auditing.incremental import (
    catalog_snapshot_hash,
    merge_product_snapshot_hashes,
    merge_score_contributions,
    score_contributions_from_summary,
)
from catora_api.auditing.scoring import (
    ScoreContribution,
    calculate_health_from_contributions,
)


def _contribution(
    *,
    product_id: str,
    outcome: str,
    weight: int = 5,
) -> ScoreContribution:
    return ScoreContribution(
        rule_key="tax.sofas_sectionals.width_mm",
        rule_version_id="rule-version",
        product_id=product_id,
        variant_id=None,
        check_key="presence",
        dimension="completeness",
        weight=weight,
        outcome=outcome,
        coverage_basis_points=10000,
    )


def test_incremental_score_merge_matches_full_recomputation() -> None:
    previous = (
        _contribution(product_id="p1", outcome="failed"),
        _contribution(product_id="p2", outcome="passed"),
    )
    current = (_contribution(product_id="p1", outcome="passed"),)

    merged = merge_score_contributions(
        previous,
        target_product_ids={"p1"},
        current=current,
    )
    incremental = calculate_health_from_contributions(merged)
    full = calculate_health_from_contributions(
        (
            _contribution(product_id="p1", outcome="passed"),
            _contribution(product_id="p2", outcome="passed"),
        )
    )

    assert incremental == full
    assert incremental.overall.score_basis_points == 10000


def test_previous_score_summary_round_trips_contributions() -> None:
    summary = {
        "overall": {
            "contributions": [
                {
                    "rule_key": "tax.sofas_sectionals.width_mm",
                    "rule_version_id": "rule-version",
                    "product_id": "p1",
                    "variant_id": None,
                    "check_key": "presence",
                    "dimension": "completeness",
                    "weight": 5,
                    "outcome": "failed",
                    "coverage_basis_points": 9000,
                }
            ]
        }
    }

    contributions = score_contributions_from_summary(summary)

    assert len(contributions) == 1
    assert contributions[0].product_id == "p1"
    assert contributions[0].coverage_basis_points == 9000


def test_snapshot_hash_merge_removes_deleted_and_updates_changed_products() -> None:
    merged = merge_product_snapshot_hashes(
        {"p1": "a" * 64, "p2": "b" * 64, "deleted": "c" * 64},
        target_product_ids={"p1", "deleted"},
        current={"p1": "d" * 64},
    )

    assert merged == {"p1": "d" * 64, "p2": "b" * 64}
    assert catalog_snapshot_hash(merged) == catalog_snapshot_hash(
        {"p2": "b" * 64, "p1": "d" * 64}
    )
