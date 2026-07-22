from __future__ import annotations

import uuid

from catora_api.auditing.lifecycle import finding_count_summary, next_finding_status
from catora_api.auditing.service import _snapshot_bytes
from catora_api.auditing.types import AttributeSnapshot, ProductAuditSnapshot


def test_finding_lifecycle_distinguishes_new_ongoing_and_regressed() -> None:
    assert next_finding_status(None) == "new"
    assert next_finding_status("new") == "ongoing"
    assert next_finding_status("ongoing") == "ongoing"
    assert next_finding_status("regressed") == "ongoing"
    assert next_finding_status("resolved") == "regressed"


def test_finding_count_summary_exposes_open_and_resolved_totals() -> None:
    summary = finding_count_summary(
        ["new", "new", "ongoing", "regressed"],
        resolved_count=3,
    )

    assert summary == {
        "new": 2,
        "ongoing": 1,
        "regressed": 1,
        "resolved": 3,
        "open_total": 4,
    }


def test_source_snapshot_serialization_is_reproducible_and_value_sensitive() -> None:
    product_id = uuid.uuid4()
    first = ProductAuditSnapshot(
        product_id=product_id,
        category_key="sofas_sectionals",
        attributes={
            "width_mm": AttributeSnapshot(
                key="width_mm",
                value=2100.0,
                value_type="decimal",
                unit="mm",
            )
        },
        source_coverage_basis_points=10000,
    )
    reordered = ProductAuditSnapshot(
        product_id=product_id,
        category_key="sofas_sectionals",
        attributes={
            "width_mm": AttributeSnapshot(
                key="width_mm",
                value=2100.0,
                value_type="decimal",
                unit="mm",
            )
        },
        source_coverage_basis_points=10000,
    )
    changed = ProductAuditSnapshot(
        product_id=product_id,
        category_key="sofas_sectionals",
        attributes={
            "width_mm": AttributeSnapshot(
                key="width_mm",
                value=2200.0,
                value_type="decimal",
                unit="mm",
            )
        },
        source_coverage_basis_points=10000,
    )

    assert _snapshot_bytes(first) == _snapshot_bytes(reordered)
    assert _snapshot_bytes(first) != _snapshot_bytes(changed)
