from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from catora_api.auditing._structured_quality import (
    STRUCTURED_DATA_ALGORITHM_VERSION,
    StructuredDataRuleConfigurationError,
    evaluate_structured_data_rule,
    is_structured_data_rule,
)
from catora_api.db.models.audit import RuleDefinition, RuleVersion
from catora_api.db.models.catalog import Category, TaxonomyField

STRUCTURED_RULE_SUFFIX = "structured_data_coverage"
STRUCTURED_RULE_TYPE = "taxonomy_field_requirement"
_ACCEPTED_PATH_TOKENS = ("structured", "jsonld", "json_ld", "schema_org")

__all__ = [
    "STRUCTURED_DATA_ALGORITHM_VERSION",
    "StructuredDataRuleConfigurationError",
    "ensure_standard_structured_data_rules",
    "evaluate_structured_data_rule",
    "is_structured_data_rule",
    "structured_rule_key",
]


async def ensure_standard_structured_data_rules(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    taxonomy_version: str,
) -> None:
    rows = (
        await session.execute(
            select(TaxonomyField, Category)
            .join(Category, Category.id == TaxonomyField.category_id)
            .where(
                TaxonomyField.workspace_id == workspace_id,
                TaxonomyField.version == taxonomy_version,
                TaxonomyField.is_immutable.is_(True),
                Category.workspace_id == workspace_id,
                Category.taxonomy_version == taxonomy_version,
                Category.is_immutable.is_(True),
            )
            .order_by(Category.key, TaxonomyField.key)
        )
    ).all()
    eligible = [
        (field, category)
        for field, category in rows
        if _schema_property(field.specification) is not None
        and _requirement(field.specification) in {"required", "recommended"}
    ]
    for field, category in eligible:
        await _ensure_rule(
            session,
            workspace_id=workspace_id,
            taxonomy_version=taxonomy_version,
            field=field,
            category=category,
        )


async def _ensure_rule(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    taxonomy_version: str,
    field: TaxonomyField,
    category: Category,
) -> None:
    rule_key = structured_rule_key(category.key, field.key)
    name = f"{category.label}: {field.label} structured-data coverage"
    description = (
        f"Checks structured-data evidence coverage for {field.key} in category {category.key}."
    )
    definition = await session.scalar(
        select(RuleDefinition).where(
            RuleDefinition.workspace_id == workspace_id,
            RuleDefinition.key == rule_key,
        )
    )
    if definition is None:
        definition = RuleDefinition(
            workspace_id=workspace_id,
            key=rule_key,
            name=name,
            rule_type=STRUCTURED_RULE_TYPE,
            description=description,
        )
        session.add(definition)
        await session.flush()
    elif (
        definition.name != name
        or definition.rule_type != STRUCTURED_RULE_TYPE
        or definition.description != description
    ):
        raise StructuredDataRuleConfigurationError(
            f"Standard structured-data rule definition {rule_key!r} has immutable drift"
        )

    expected = _specification(
        category_key=category.key,
        taxonomy_version=taxonomy_version,
        field=field,
    )
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
        await session.flush()
    elif (
        not version.is_immutable
        or _canonical_json(version.specification) != _canonical_json(expected)
    ):
        raise StructuredDataRuleConfigurationError(
            f"Standard structured-data rule {rule_key!r}@{taxonomy_version} has immutable drift"
        )


def _specification(
    *,
    category_key: str,
    taxonomy_version: str,
    field: TaxonomyField,
) -> dict[str, object]:
    source = field.specification
    mapping = _mapping(source.get("mapping"))
    schema_property = _schema_property(source)
    if schema_property is None:
        raise StructuredDataRuleConfigurationError(
            f"Field {category_key}.{field.key} has no Schema.org property"
        )
    requirement = _requirement(source)
    if requirement not in {"required", "recommended"}:
        raise StructuredDataRuleConfigurationError(
            f"Field {category_key}.{field.key} is not eligible for structured-data auditing"
        )
    return {
        "category_key": category_key,
        "field_key": field.key,
        "requirement": requirement,
        "severity": "high" if requirement == "required" else "medium",
        "field": {
            "category_key": category_key,
            "key": field.key,
            "label": field.label,
            "scope": _required_string(source, "scope"),
            "data_type": field.data_type,
            "canonical_unit": source.get("canonical_unit"),
            "allowed_values": list(_string_tuple(source.get("allowed_values"))),
            "markets": list(_string_tuple(source.get("markets"))),
            "constraints": {
                "structured_data_quality_kind": "evidence_coverage",
                "accepted_path_tokens": list(_ACCEPTED_PATH_TOKENS),
                "schema_org_property": schema_property,
            },
            "mapping": dict(mapping),
            "taxonomy_version": taxonomy_version,
            "structured_data_algorithm_version": STRUCTURED_DATA_ALGORITHM_VERSION,
        },
    }


def structured_rule_key(category_key: str, field_key: str) -> str:
    return f"builtin.{category_key}.{field_key}.{STRUCTURED_RULE_SUFFIX}"


def _schema_property(specification: Mapping[str, object]) -> str | None:
    mapping = _mapping(specification.get("mapping"))
    value = mapping.get("schema_org_property")
    return value if isinstance(value, str) and value else None


def _requirement(specification: Mapping[str, object]) -> str:
    value = specification.get("requirement")
    return value if isinstance(value, str) else "optional"


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _required_string(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise StructuredDataRuleConfigurationError(
            f"Structured-data field {key!r} must be a non-empty string"
        )
    return value


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
