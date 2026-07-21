from __future__ import annotations

import uuid
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql

from catora_api.db import Base
from catora_api.db.models import (
    AuditFinding,
    EvidenceReference,
    Product,
    ProductAttribute,
    Recommendation,
    RuleVersion,
    SourceRecord,
    TaxonomyField,
)
from catora_api.repositories import WorkspaceRepository
from catora_api.schemas import OPENAPI_EXAMPLES, BuyerIntentCreate, SourceCreate
from tests.factories import product_factory

REQUIRED_TABLES = {
    "organizations",
    "workspaces",
    "users",
    "memberships",
    "storefronts",
    "markets",
    "catalog_sources",
    "ingestion_jobs",
    "source_records",
    "products",
    "product_variants",
    "product_images",
    "product_attributes",
    "categories",
    "taxonomy_fields",
    "evidence_references",
    "audit_runs",
    "audit_findings",
    "rule_definitions",
    "rule_versions",
    "buyer_intents",
    "intent_runs",
    "intent_product_matches",
    "recommendations",
    "recommendation_fields",
    "review_decisions",
    "change_sets",
    "market_comparisons",
    "market_conflicts",
    "report_jobs",
    "export_artifacts",
    "measurement_baselines",
    "product_cohorts",
    "audit_events",
}


def test_required_domain_tables_are_registered() -> None:
    assert set(Base.metadata.tables) >= REQUIRED_TABLES


def test_business_tables_are_workspace_scoped() -> None:
    exceptions = {"organizations", "workspaces", "users", "memberships", "system_metadata"}
    for name, table in Base.metadata.tables.items():
        if name in exceptions:
            continue
        assert "workspace_id" in table.c, f"{name} is missing workspace_id"
        workspace_fks = {fk.target_fullname for fk in table.c.workspace_id.foreign_keys}
        assert workspace_fks == {"workspaces.id"}


def test_provenance_chain_foreign_keys_are_explicit() -> None:
    evidence_targets = {
        fk.target_fullname for fk in EvidenceReference.__table__.c.source_record_id.foreign_keys
    }
    attribute_targets = {
        fk.target_fullname for fk in EvidenceReference.__table__.c.attribute_id.foreign_keys
    }
    assert evidence_targets == {"source_records.id"}
    assert attribute_targets == {"product_attributes.id"}
    assert SourceRecord.__table__.c.payload.type.__class__.__name__ == "JSONB"


def test_versioned_entities_expose_immutability() -> None:
    assert "is_immutable" in RuleVersion.__table__.c
    assert "is_immutable" in TaxonomyField.__table__.c
    assert RuleVersion.__table__.c.is_immutable.default.arg is True


def test_workspace_repository_always_adds_tenant_predicate() -> None:
    workspace_id = uuid.uuid4()
    product_id = uuid.uuid4()
    repository = WorkspaceRepository(Mock(), Product, workspace_id)
    sql = str(
        repository.select_by_id(product_id).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "products.workspace_id" in sql
    assert str(workspace_id) in sql
    assert "products.id" in sql
    assert str(product_id) in sql


def test_workspace_repository_rejects_cross_workspace_entity() -> None:
    workspace_id = uuid.uuid4()
    repository = WorkspaceRepository(Mock(), Product, workspace_id)
    product = product_factory(workspace_id=uuid.uuid4())
    with pytest.raises(PermissionError):
        repository.assert_workspace(product)


def test_contract_examples_validate() -> None:
    source = SourceCreate.model_validate(OPENAPI_EXAMPLES["source_create"])
    intent = BuyerIntentCreate.model_validate(OPENAPI_EXAMPLES["buyer_intent_create"])
    assert source.source_type == "shopify"
    assert "220 cm" in intent.query


def test_historical_models_have_snapshot_or_version_columns() -> None:
    assert "source_snapshot_hash" in Recommendation.__table__.c
    assert "rule_version_id" in AuditFinding.__table__.c
    assert "transformer_version" in ProductAttribute.__table__.c
