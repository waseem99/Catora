from __future__ import annotations

import uuid

import pytest

from catora_api.auditing.append_only_service import _category_keys, _market_codes
from catora_api.auditing.service import AuditConfigurationError
from catora_api.auditing.types import FindingCandidate
from catora_api.db.models.audit import AuditFinding
from catora_api.main import app
from catora_api.schemas.audits import AuditFindingListResponse, AuditFindingView


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


class MarketRowResult:
    def __init__(self, rows: list[tuple[uuid.UUID, str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[uuid.UUID, str]]:
        return self._rows


class MarketSnapshotSession:
    def __init__(self, rows: list[tuple[uuid.UUID, str]]) -> None:
        self._rows = rows

    async def execute(self, _statement: object) -> MarketRowResult:
        return MarketRowResult(self._rows)


def _candidate(
    rule_version_id: uuid.UUID,
    *,
    product_id: uuid.UUID | None = None,
) -> FindingCandidate:
    return FindingCandidate(
        fingerprint="a" * 64,
        rule_version_id=rule_version_id,
        product_id=product_id or uuid.uuid4(),
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
async def test_market_snapshot_comes_from_product_provenance() -> None:
    workspace_id = uuid.uuid4()
    product_id = uuid.uuid4()
    candidate = _candidate(uuid.uuid4(), product_id=product_id)
    session = MarketSnapshotSession(
        [
            (product_id, "SA"),
            (product_id, "AE"),
            (product_id, "SA"),
        ]
    )

    market_codes = await _market_codes(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        findings={candidate.fingerprint: candidate},
    )

    assert market_codes == {product_id: ["AE", "SA"]}


@pytest.mark.asyncio
async def test_market_snapshot_keeps_unmapped_products_explicit() -> None:
    workspace_id = uuid.uuid4()
    product_id = uuid.uuid4()
    candidate = _candidate(uuid.uuid4(), product_id=product_id)
    session = MarketSnapshotSession([])

    market_codes = await _market_codes(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        findings={candidate.fingerprint: candidate},
    )

    assert market_codes == {product_id: []}


def test_finding_query_indexes_match_supported_filters() -> None:
    run_index = next(
        item
        for item in AuditFinding.__table__.indexes
        if item.name == "ix_audit_findings_run_query"
    )
    market_index = next(
        item
        for item in AuditFinding.__table__.indexes
        if item.name == "ix_audit_findings_market_codes"
    )

    assert [column.name for column in run_index.columns] == [
        "workspace_id",
        "audit_run_id",
        "category_key",
        "field_key",
        "remediation_type",
    ]
    assert [column.name for column in market_index.columns] == ["market_codes"]
    assert market_index.dialect_options["postgresql"]["using"] == "gin"


def test_finding_endpoint_exposes_complete_filter_contract() -> None:
    path = "/api/v1/workspaces/{workspace_id}/audit-runs/{run_id}/findings"
    operation = app.openapi()["paths"][path]["get"]
    query_and_path_parameter_names = {
        parameter["name"]
        for parameter in operation["parameters"]
        if parameter["in"] in {"query", "path"}
    }

    assert query_and_path_parameter_names == {
        "workspace_id",
        "run_id",
        "status",
        "severity",
        "category_key",
        "field_key",
        "market",
        "business_impact",
        "remediation_type",
        "product_id",
        "offset",
        "limit",
    }


def test_finding_endpoint_returns_reconcilable_pagination_metadata() -> None:
    path = "/api/v1/workspaces/{workspace_id}/audit-runs/{run_id}/findings"
    schema = app.openapi()["paths"][path]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    assert schema["$ref"].endswith("/AuditFindingListResponse")
    assert set(AuditFindingListResponse.model_fields) == {
        "items",
        "total",
        "offset",
        "limit",
    }
    assert "market_codes" in AuditFindingView.model_fields
