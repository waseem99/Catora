from __future__ import annotations

import uuid

import pytest

from catora_api.db.models.audit import RuleDefinition, RuleVersion
from catora_api.db.models.catalog import Category, TaxonomyField
from catora_api.taxonomy.compiler import TaxonomyCompiler, build_compile_plan
from catora_api.taxonomy.loader import load_bundled_taxonomy


class EmptyScalarResult:
    def all(self) -> list[Category]:
        return []


class RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    async def scalars(self, _statement: object) -> EmptyScalarResult:
        return EmptyScalarResult()

    async def scalar(self, _statement: object) -> None:
        return None

    def add(self, value: object) -> None:
        if (
            isinstance(value, Category | TaxonomyField | RuleDefinition | RuleVersion)
            and value.id is None
        ):
            value.id = uuid.uuid4()
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def test_compile_plan_is_deterministic_and_resolves_requirement_sources() -> None:
    package = load_bundled_taxonomy()

    first = build_compile_plan(package)
    second = build_compile_plan(package)

    assert first == second
    assert len(first.categories) == len(package.categories)
    sofa = next(category for category in first.categories if category.key == "sofas_sectionals")
    width = next(field for field in sofa.fields if field.field_key == "width_mm")
    assert width.requirement == "required"
    assert width.specification["requirement_source"] == "furniture"
    assert width.specification["taxonomy_fingerprint"] == first.fingerprint


@pytest.mark.asyncio
async def test_compiler_creates_immutable_categories_fields_and_rules() -> None:
    package = load_bundled_taxonomy()
    plan = build_compile_plan(package)
    session = RecordingSession()

    summary = await TaxonomyCompiler().compile(
        session,  # type: ignore[arg-type]
        workspace_id=uuid.uuid4(),
        package=package,
    )

    expected_rule_count = sum(
        field.requirement in {"required", "recommended"}
        for category in plan.categories
        for field in category.fields
    )
    categories = [value for value in session.added if isinstance(value, Category)]
    fields = [value for value in session.added if isinstance(value, TaxonomyField)]
    definitions = [
        value for value in session.added if isinstance(value, RuleDefinition)
    ]
    versions = [value for value in session.added if isinstance(value, RuleVersion)]

    assert summary.categories_created == len(plan.categories)
    assert summary.fields_created == sum(len(category.fields) for category in plan.categories)
    assert summary.rule_definitions_created == expected_rule_count
    assert summary.rule_versions_created == expected_rule_count
    assert len(categories) == summary.categories_created
    assert len(fields) == summary.fields_created
    assert len(definitions) == expected_rule_count
    assert len(versions) == expected_rule_count
    assert all(category.is_immutable for category in categories)
    assert all(field.is_immutable for field in fields)
    assert all(version.is_immutable for version in versions)
    assert session.commits == 1
