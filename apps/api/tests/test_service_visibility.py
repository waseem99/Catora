# ruff: noqa: E501
from __future__ import annotations

import hashlib
import hmac
import io
import time
import uuid

import pytest
from pptx import Presentation

from catora_api.schemas.service_visibility import ServicePageSnapshot
from catora_api.service_visibility.classification import classify_page
from catora_api.service_visibility.engine import build_scorecard
from catora_api.service_visibility.extraction import extract_page
from catora_api.service_visibility.questions import build_default_questions
from catora_api.service_visibility.reports import executive_pptx, findings_csv
from catora_api.service_visibility.security import issue_token, verify_signed_body


HTML = """
<html><head><title>Cloud Consulting Services</title><meta name="description" content="Cloud consulting for growing teams"><link rel="canonical" href="https://example.com/services/cloud"><script type="application/ld+json">{"@type":"Organization","name":"Example Co"}</script></head><body><h1>Cloud Consulting Services</h1><p>Our process starts with discovery and produces measurable project outcomes for healthcare teams.</p><p>Book a consultation to get started.</p><a href="/case-studies/acme">Case study</a></body></html>
"""


def page() -> ServicePageSnapshot:
    return extract_page("https://example.com/services/cloud", HTML)


def test_extracts_and_classifies_service_page() -> None:
    snapshot = page()
    assert snapshot.h1 == "Cloud Consulting Services"
    assert classify_page(snapshot).page_type == "service"
    assert str(snapshot.internal_links[0]) == "https://example.com/case-studies/acme"


def test_default_suite_has_25_deterministic_questions() -> None:
    first = build_default_questions([page()])
    second = build_default_questions([page()])
    assert len(first) == 25
    assert [item.question_hash for item in first] == [item.question_hash for item in second]
    assert {item.question_type for item in first} >= {
        "definition",
        "fit",
        "problem",
        "outcome",
        "process",
        "timing",
        "cost",
        "proof",
        "expertise",
        "security",
        "limitations",
    }


def test_scorecard_has_evidence_backed_findings_and_questions() -> None:
    scorecard = build_scorecard(uuid.uuid4(), uuid.uuid4(), [page()])
    assert scorecard.page_count == 1
    assert 0 <= scorecard.score_basis_points <= 10_000
    assert len(scorecard.questions) == 25
    assert all(item.rule_version for item in scorecard.findings)
    assert "answer.missing_process" not in {item.rule_id for item in scorecard.findings}
    assert "evidence.missing_proof" not in {item.rule_id for item in scorecard.findings}


def test_reports_are_valid_editable_pptx_and_csv() -> None:
    scorecard = build_scorecard(uuid.uuid4(), uuid.uuid4(), [page()])
    assert findings_csv(scorecard).startswith(b"severity,category")
    presentation = Presentation(io.BytesIO(executive_pptx(scorecard)))
    assert len(presentation.slides) == 4
    assert "Catora Service Visibility Audit" in presentation.slides[0].shapes[0].text


def test_signed_bridge_body_accepts_current_signature_and_rejects_changes() -> None:
    token, digest, _ = issue_token()
    body = b'{"pages":[]}'
    timestamp = str(int(time.time()))
    signature = hmac.new(
        token.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    verify_signed_body(
        token=token,
        expected_token_hash=digest,
        timestamp=timestamp,
        signature=signature,
        body=body,
    )
    with pytest.raises(ValueError, match="signature"):
        verify_signed_body(
            token=token,
            expected_token_hash=digest,
            timestamp=timestamp,
            signature=signature,
            body=body + b" ",
        )


def test_signed_bridge_body_rejects_stale_timestamp() -> None:
    token, digest, _ = issue_token()
    body = b"{}"
    timestamp = "2000000000"
    signature = hmac.new(
        token.encode(),
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    with pytest.raises(ValueError, match="clock skew"):
        verify_signed_body(
            token=token,
            expected_token_hash=digest,
            timestamp=timestamp,
            signature=signature,
            body=body,
        )
