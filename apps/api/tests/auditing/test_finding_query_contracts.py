from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from catora_api.auditing.append_only_service import _category_keys
from catora_api.auditing.service import AuditConfigurationError
from catora_api.auditing.types import FindingCandidate
from catora_api.db.models.audit import AuditFinding
from catora_api.main import app
from catora_api.schemas.audits import AuditFindingView


class RowResult:
    def __init__(self, rows: list[tuple[uuid.UUID, dict[str, object]]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[uuid.UUID, dict[str, object]]]:
        return self._rows


class RuleVersionSession:
    def __init__(self, rows: list[tuple[uuid.UUID, dict[str, object]]]) -> None:
        self._rows = rows

    async def execute(self, _statement: object) -> RowResult:
        return RowResult(self._rows)


def _candidate(rule_version_id: uuid.UUID) -> FindingCandidate:
    return FindingCandidate(
        fingerprint="a" * 64,
        rule_version_id=rule_version_id,
        product_id=uuid.uuid4(),
        variant_id=None,
        severity="high",
        title="Width missing",
        explanation="Width is required",
        field_key="width_mm",
        affected_value=None,
        evidence=(),
        business_impact="data_quality",
        remediation_type="supply_source_value",
        failure_codes=("missing_value",),
    )


@pytest.mark.asyncio
async def test_category_snapshot_comes_from_immutable_rule_version() -> None:
    rule_version_id = uuid.uuid4()
    candidate = _candidate(rule_version_id)
    session = RuleVersionSession(
        [(rule_version_id, {"category_key": "sofas_sectionals"})]
    )

    category_keys = await _category_keys(
        session,  # type: ignore[arg-type]
        {candidate.fingerprint: candidate},
    )

    assert category_keys == {rule_version_id: "sofas_sectionals"}


@pytest.mark.asyncio
async def test_category_snapshot_rejects_malformed_rule_version() -> None:
    rule_version_id = uuid.uuid4()
    candidate = _candidate(rule_version_id)
    session = RuleVersionSession([(rule_version_id, {})])

    with pytest.raises(AuditConfigurationError, match="category key"):
        await _category_keys(
            session,  # type: ignore[arg-type]
            {candidate.fingerprint: candidate},
        )


@pytest.mark.asyncio
async def test_category_snapshot_rejects_missing_rule_version() -> None:
    rule_version_id = uuid.uuid4()
    candidate = _candidate(rule_version_id)

    with pytest.raises(AuditConfigurationError, match="missing category snapshots"):
        await _category_keys(
            RuleVersionSession([]),  # type: ignore[arg-type]
            {candidate.fingerprint: candidate},
        )


def test_finding_query_index_matches_supported_filters() -> None:
    index = next(
        item
        for item in AuditFinding.__table__.indexes
        if item.name == "ix_audit_findings_run_query"
    )

    assert [column.name for column in index.columns] == [
        "workspace_id",
        "audit_run_id",
        "category_key",
        "field_key",
        "remediation_type",
    ]


def test_finding_response_schema_exposes_category_snapshot() -> None:
    now = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    finding = AuditFindingView.model_validate(
        {
            "id": uuid.uuid4(),
            "audit_run_id": uuid.uuid4(),
            "previous_finding_id": None,
            "rule_version_id": uuid.uuid4(),
            "product_id": uuid.uuid4(),
            "variant_id": None,
            "severity": "high",
            "title": "Width missing",
            "explanation": "Width is required",
            "fingerprint": "a" * 64,
            "status": "new",
            "category_key": "sofas_sectionals",
            "field_key": "width_mm",
            "affected_value": None,
            "business_impact": "data_quality",
            "remediation_type": "supply_source_value",
            "failure_codes": ["missing_value"],
            "evidence": [],
            "first_seen_at": now,
            "last_seen_at": now,
            "resolved_at": None,
            "created_at": now,
            "updated_at": now,
        }
    )

    assert finding.category_key == "sofas_sectionals"


def test_finding_endpoint_exposes_complete_filter_contract() -> None:
    path = "/api/v1/workspaces/{workspace_id}/audit-runs/{run_id}/findings"
    operation = app.openapi()["paths"][path]["get"]
    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}

    assert set(parameters) == {
        "workspace_id",
        "run_id",
        "status",
        "severity",
        "category_key",
        "field_key",
        "business_impact",
        "remediation_type",
        "product_id",
        "offset",
        "limit",
    }
    assert parameters["offset"]["schema"]["minimum"] == 0
    assert parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["limit"]["schema"]["maximum"] == 500
    assert _schema_value(parameters["category_key"]["schema"], "pattern") == (
        "^[a-z][a-z0-9_]*$"
    )
    assert _schema_value(parameters["field_key"]["schema"], "pattern") == (
        "^[a-z][a-z0-9_]*$"
    )
    assert _schema_value(parameters["remediation_type"]["schema"], "pattern") == (
        "^[a-z][a-z0-9_]*$"
    )


def _schema_value(schema: dict[str, object], key: str) -> object | None:
    value = schema.get(key)
    if value is not None:
        return value
    alternatives = schema.get("anyOf")
    if isinstance(alternatives, list):
        for alternative in alternatives:
            if isinstance(alternative, dict) and key in alternative:
                return alternative[key]
    return None
