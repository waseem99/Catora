from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from catora_api.auditing.restaurant_rules import (
    RESTAURANT_AUDIT_PACK_VERSION,
    RestaurantWebPageSnapshot,
    evaluate_restaurant_pages,
    restaurant_audit_pack,
)
from catora_api.auditing.types import EvidenceSnapshot

OBSERVED_AT = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _page(**overrides: object) -> RestaurantWebPageSnapshot:
    values: dict[str, object] = {
        "page_id": uuid.uuid4(),
        "page_type": "location",
        "url": "https://example.test/locations/lahore",
        "status_code": 200,
        "indexable": True,
        "robots_allowed": True,
        "sitemap_listed": True,
        "canonical_url": "https://example.test/locations/lahore/",
        "title": "North Grill Lahore Restaurant and Delivery",
        "meta_description": (
            "Visit North Grill Lahore for verified hours, menu information, "
            "facilities, takeaway and delivery details."
        ),
        "h1": "North Grill Lahore",
        "body_text": " ".join(["verified restaurant location content"] * 60),
        "rendered_text": " ".join(["verified restaurant location content"] * 60),
        "structured_data_types": ("Restaurant", "PostalAddress"),
        "internal_link_count": 8,
        "response_time_ms": 650,
        "observed_at": OBSERVED_AT,
        "volatile_fact_observed_at": OBSERVED_AT - timedelta(days=2),
        "evidence": (
            EvidenceSnapshot(
                source_record_id=uuid.uuid4(),
                field_path="$.page",
                excerpt="North Grill Lahore",
            ),
        ),
    }
    values.update(overrides)
    return RestaurantWebPageSnapshot(**values)  # type: ignore[arg-type]


def _failure_codes(page: RestaurantWebPageSnapshot) -> set[str]:
    return {
        code
        for evaluation in evaluate_restaurant_pages((page,), as_of=OBSERVED_AT)
        if evaluation.finding is not None
        for code in evaluation.finding.failure_codes
    }


def test_pack_is_versioned_and_stable() -> None:
    first = restaurant_audit_pack()
    second = restaurant_audit_pack()
    assert first.version == RESTAURANT_AUDIT_PACK_VERSION
    assert first.rules == second.rules
    assert len(first.rules) == 50
    assert len({rule.rule_version_id for rule in first.rules}) == 50


def test_healthy_location_page_passes_specialized_rules() -> None:
    codes = _failure_codes(_page())
    assert "page_not_indexable" not in codes
    assert "robots_blocked" not in codes
    assert "missing_from_sitemap" not in codes
    assert "canonical_target_mismatch" not in codes
    assert "required_restaurant_schema_missing" not in codes
    assert "content_hidden_after_render" not in codes
    assert "thin_restaurant_page" not in codes
    assert "volatile_restaurant_fact_stale" not in codes
    assert "bot_or_waf_access_blocked" not in codes


def test_indexability_canonical_schema_and_access_fail_closed() -> None:
    page = _page(
        status_code=403,
        indexable=False,
        robots_allowed=False,
        sitemap_listed=False,
        canonical_url="https://example.test/locations/karachi",
        structured_data_types=("WebPage",),
        body_text="Access denied. Complete the CAPTCHA bot verification.",
        rendered_text="Access denied.",
    )
    codes = _failure_codes(page)
    assert {
        "page_not_indexable",
        "robots_blocked",
        "missing_from_sitemap",
        "canonical_target_mismatch",
        "required_restaurant_schema_missing",
        "thin_restaurant_page",
        "bot_or_waf_access_blocked",
    }.issubset(codes)


def test_rendered_hidden_content_is_detected() -> None:
    page = _page(
        body_text=" ".join(["menu and branch evidence"] * 100),
        rendered_text="Loading menu",
    )
    assert "content_hidden_after_render" in _failure_codes(page)


def test_stale_menu_facts_are_detected_without_inference() -> None:
    page = _page(
        page_type="menu_item",
        structured_data_types=("MenuItem",),
        volatile_fact_observed_at=OBSERVED_AT - timedelta(days=8),
    )
    assert "volatile_restaurant_fact_stale" in _failure_codes(page)


def test_evaluations_are_deterministic_under_repeated_execution() -> None:
    page = _page(indexable=False, structured_data_types=("WebPage",))
    first = evaluate_restaurant_pages((page,), as_of=OBSERVED_AT)
    second = evaluate_restaurant_pages((page,), as_of=OBSERVED_AT)
    assert first == second
    assert [evaluation.finding.fingerprint for evaluation in first if evaluation.finding] == [
        evaluation.finding.fingerprint for evaluation in second if evaluation.finding
    ]


def test_page_validation_rejects_future_or_naive_observations() -> None:
    page_id = uuid.uuid4()
    try:
        RestaurantWebPageSnapshot(
            page_id=page_id,
            page_type="menu",
            url="https://example.test/menu",
            status_code=200,
            indexable=True,
            robots_allowed=True,
            sitemap_listed=True,
            canonical_url="https://example.test/menu",
            title="Menu",
            meta_description=None,
            h1="Menu",
            body_text="Menu",
            rendered_text=None,
            structured_data_types=("Menu",),
            internal_link_count=1,
            response_time_ms=100,
            observed_at=datetime(2026, 8, 1, 12, 0),
        )
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("Naive observation time should be rejected")
