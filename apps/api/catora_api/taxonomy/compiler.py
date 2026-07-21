from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.db.models.audit import RuleDefinition, RuleVersion
from catora_api.db.models.catalog import Category, TaxonomyField
from catora_api.taxonomy.resolution import ResolvedCategory, resolve_categories
from catora_api.taxonomy.schema import Requirement, TaxonomyFieldDefinition, TaxonomyPackage


class TaxonomyImmutabilityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CompiledFieldPlan:
    category_key: str
    field_key: str
    field_label: str
    data_type: str
    requirement: Requirement
    specification: dict[str, object]


@dataclass(frozen=True, slots=True)
class CompiledCategoryPlan:
    key: str
    label: str
    parent_key: str | None
    depth: int
    fields: tuple[CompiledFieldPlan, ...]


@dataclass(frozen=True, slots=True)
class TaxonomyCompilePlan:
    vertical: str
    version: str
    fingerprint: str
    categories: tuple[CompiledCategoryPlan, ...]


@dataclass(frozen=True, slots=True)
class TaxonomyCompileSummary:
    categories_created: int
    fields_created: int
    rule_definitions_created: int
    rule_versions_created: int
    fingerprint: str


def build_compile_plan(package: TaxonomyPackage) -> TaxonomyCompilePlan:
    fields_by_key = {field.key: field for field in package.fields}
    definitions = {category.key: category for category in package.categories}
    fingerprint = taxonomy_fingerprint(package)
    categories = tuple(
        CompiledCategoryPlan(
            key=category.key,
            label=category.label,
            parent_key=definitions[category.key].parent_key,
            depth=len(category.parent_chain),
            fields=tuple(
                _field_plan(
                    package=package,
                    category=category,
                    field=fields_by_key[field_key],
                    fingerprint=fingerprint,
                )
                for field_key in sorted(fields_by_key)
            ),
        )
        for category in sorted(
            resolve_categories(package).values(),
            key=lambda item: (len(item.parent_chain), item.key),
        )
    )
    return TaxonomyCompilePlan(
        vertical=package.vertical,
        version=package.version,
        fingerprint=fingerprint,
        categories=categories,
    )


def taxonomy_fingerprint(package: TaxonomyPackage) -> str:
    payload = _canonical_json(package.model_dump(mode="json"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TaxonomyCompiler:
    async def compile(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        package: TaxonomyPackage,
    ) -> TaxonomyCompileSummary:
        plan = build_compile_plan(package)
        existing = (
            await session.scalars(
                select(Category).where(
                    Category.workspace_id == workspace_id,
                    Category.taxonomy_version == plan.version,
                )
            )
        ).all()
        if existing:
            await self._verify_existing(
                session,
                workspace_id=workspace_id,
                plan=plan,
                categories=existing,
            )
            return TaxonomyCompileSummary(0, 0, 0, 0, plan.fingerprint)

        category_count = 0
        field_count = 0
        definition_count = 0
        version_count = 0
        categories_by_key: dict[str, Category] = {}
        for category_plan in plan.categories:
            parent = (
                categories_by_key[category_plan.parent_key]
                if category_plan.parent_key is not None
                else None
            )
            category = Category(
                workspace_id=workspace_id,
                parent_id=parent.id if parent is not None else None,
                key=category_plan.key,
                label=category_plan.label,
                taxonomy_version=plan.version,
                is_immutable=True,
            )
            session.add(category)
            await session.flush()
            categories_by_key[category_plan.key] = category
            category_count += 1

            for field_plan in category_plan.fields:
                session.add(
                    TaxonomyField(
                        workspace_id=workspace_id,
                        category_id=category.id,
                        key=field_plan.field_key,
                        label=field_plan.field_label,
                        data_type=field_plan.data_type,
                        version=plan.version,
                        specification=field_plan.specification,
                        is_immutable=True,
                    )
                )
                field_count += 1
                if field_plan.requirement not in {"required", "recommended"}:
                    continue
                created_definition, created_version = await self._ensure_rule(
                    session,
                    workspace_id=workspace_id,
                    taxonomy_version=plan.version,
                    category_plan=category_plan,
                    field_plan=field_plan,
                )
                definition_count += int(created_definition)
                version_count += int(created_version)

        await session.flush()
        return TaxonomyCompileSummary(
            categories_created=category_count,
            fields_created=field_count,
            rule_definitions_created=definition_count,
            rule_versions_created=version_count,
            fingerprint=plan.fingerprint,
        )

    async def _ensure_rule(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        taxonomy_version: str,
        category_plan: CompiledCategoryPlan,
        field_plan: CompiledFieldPlan,
    ) -> tuple[bool, bool]:
        rule_key = _rule_key(category_plan.key, field_plan.field_key)
        definition = await session.scalar(
            select(RuleDefinition).where(
                RuleDefinition.workspace_id == workspace_id,
                RuleDefinition.key == rule_key,
            )
        )
        created_definition = definition is None
        if definition is None:
            definition = RuleDefinition(
                workspace_id=workspace_id,
                key=rule_key,
                name=f"{category_plan.label}: {field_plan.field_label}",
                rule_type="taxonomy_field_requirement",
                description=(
                    f"Checks {field_plan.requirement} field "
                    f"{field_plan.field_key} for {category_plan.key}."
                ),
            )
            session.add(definition)
            await session.flush()
        else:
            _verify_rule_definition(definition, rule_key=rule_key)

        expected = _rule_specification(field_plan)
        version = await session.scalar(
            select(RuleVersion).where(
                RuleVersion.rule_definition_id == definition.id,
                RuleVersion.version == taxonomy_version,
            )
        )
        if version is None:
            session.add(
                RuleVersion(
                    workspace_id=workspace_id,
                    rule_definition_id=definition.id,
                    version=taxonomy_version,
                    specification=expected,
                    is_immutable=True,
                )
            )
            return created_definition, True
        if not version.is_immutable or _canonical_json(version.specification) != _canonical_json(
            expected
        ):
            raise TaxonomyImmutabilityError(
                f"rule version {rule_key!r}@{taxonomy_version} has immutable drift"
            )
        return created_definition, False

    async def _verify_existing(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        plan: TaxonomyCompilePlan,
        categories: Sequence[Category],
    ) -> None:
        expected_categories = {item.key: item for item in plan.categories}
        existing_by_key = {item.key: item for item in categories}
        if set(existing_by_key) != set(expected_categories):
            raise TaxonomyImmutabilityError(
                f"taxonomy {plan.version} already exists with a different category set"
            )
        key_by_id = {item.id: item.key for item in categories}
        for key, category in existing_by_key.items():
            expected = expected_categories[key]
            parent_key = key_by_id.get(category.parent_id) if category.parent_id else None
            if (
                category.label != expected.label
                or parent_key != expected.parent_key
                or not category.is_immutable
            ):
                raise TaxonomyImmutabilityError(
                    f"taxonomy category {key!r}@{plan.version} has immutable drift"
                )

        category_ids = [item.id for item in categories]
        fields = (
            await session.scalars(
                select(TaxonomyField).where(
                    TaxonomyField.workspace_id == workspace_id,
                    TaxonomyField.category_id.in_(category_ids),
                    TaxonomyField.version == plan.version,
                )
            )
        ).all()
        category_key_by_id = {item.id: item.key for item in categories}
        existing_fields = {
            (category_key_by_id[field.category_id], field.key): field for field in fields
        }
        expected_fields = {
            (category.key, field.field_key): field
            for category in plan.categories
            for field in category.fields
        }
        if set(existing_fields) != set(expected_fields):
            raise TaxonomyImmutabilityError(
                f"taxonomy {plan.version} already exists with a different field set"
            )
        for key, field in existing_fields.items():
            expected = expected_fields[key]
            if (
                field.label != expected.field_label
                or field.data_type != expected.data_type
                or not field.is_immutable
                or _canonical_json(field.specification)
                != _canonical_json(expected.specification)
            ):
                raise TaxonomyImmutabilityError(
                    f"taxonomy field {key!r}@{plan.version} has immutable drift"
                )
        await self._verify_existing_rules(
            session,
            workspace_id=workspace_id,
            plan=plan,
        )

    async def _verify_existing_rules(
        self,
        session: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        plan: TaxonomyCompilePlan,
    ) -> None:
        expected = {
            _rule_key(category.key, field.field_key): _rule_specification(field)
            for category in plan.categories
            for field in category.fields
            if field.requirement in {"required", "recommended"}
        }
        definitions = (
            await session.scalars(
                select(RuleDefinition).where(
                    RuleDefinition.workspace_id == workspace_id,
                    RuleDefinition.key.in_(sorted(expected)),
                )
            )
        ).all()
        by_key = {definition.key: definition for definition in definitions}
        if set(by_key) != set(expected):
            raise TaxonomyImmutabilityError(
                f"taxonomy {plan.version} already exists with a different rule set"
            )
        for rule_key, definition in by_key.items():
            _verify_rule_definition(definition, rule_key=rule_key)

        key_by_id = {definition.id: definition.key for definition in definitions}
        versions = (
            await session.scalars(
                select(RuleVersion).where(
                    RuleVersion.workspace_id == workspace_id,
                    RuleVersion.rule_definition_id.in_(list(key_by_id)),
                    RuleVersion.version == plan.version,
                )
            )
        ).all()
        versions_by_key = {key_by_id[item.rule_definition_id]: item for item in versions}
        if set(versions_by_key) != set(expected):
            raise TaxonomyImmutabilityError(
                f"taxonomy {plan.version} already exists with incomplete rule versions"
            )
        for rule_key, version in versions_by_key.items():
            if (
                not version.is_immutable
                or _canonical_json(version.specification) != _canonical_json(expected[rule_key])
            ):
                raise TaxonomyImmutabilityError(
                    f"rule version {rule_key!r}@{plan.version} has immutable drift"
                )


def _field_plan(
    *,
    package: TaxonomyPackage,
    category: ResolvedCategory,
    field: TaxonomyFieldDefinition,
    fingerprint: str,
) -> CompiledFieldPlan:
    requirement = category.requirements[field.key]
    specification = cast(dict[str, object], field.model_dump(mode="json"))
    specification.update(
        {
            "vertical": package.vertical,
            "taxonomy_version": package.version,
            "taxonomy_fingerprint": fingerprint,
            "category_key": category.key,
            "category_parent_chain": list(category.parent_chain),
            "requirement": requirement,
            "requirement_source": category.requirement_sources[field.key],
        }
    )
    return CompiledFieldPlan(
        category_key=category.key,
        field_key=field.key,
        field_label=field.label,
        data_type=field.data_type,
        requirement=requirement,
        specification=specification,
    )


def _rule_key(category_key: str, field_key: str) -> str:
    return f"tax.{category_key}.{field_key}"


def _rule_specification(field_plan: CompiledFieldPlan) -> dict[str, object]:
    return {
        "category_key": field_plan.category_key,
        "field_key": field_plan.field_key,
        "requirement": field_plan.requirement,
        "severity": "high" if field_plan.requirement == "required" else "medium",
        "field": field_plan.specification,
    }


def _verify_rule_definition(definition: RuleDefinition, *, rule_key: str) -> None:
    if definition.rule_type != "taxonomy_field_requirement":
        raise TaxonomyImmutabilityError(
            f"rule definition {rule_key!r} already exists with incompatible type"
        )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
