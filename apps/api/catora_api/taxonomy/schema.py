from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CanonicalKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
Requirement = Literal["required", "recommended", "optional", "not_applicable"]
FieldScope = Literal["product", "variant", "both"]
DataType = Literal["string", "integer", "decimal", "boolean", "date", "url", "enum", "list"]


class FieldConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum: float | None = None
    maximum: float | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    pattern: str | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> FieldConstraints:
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum cannot exceed maximum")
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError("min_length cannot exceed max_length")
        return self


class EvidenceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    minimum_sources: int = Field(default=1, ge=1, le=5)
    accepted_paths: tuple[str, ...] = ()
    approval_required: bool = False


class StructuredDataMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_org_property: str | None = None
    seo_role: str | None = None


class TaxonomyFieldDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: CanonicalKey
    label: str = Field(min_length=1, max_length=200)
    data_type: DataType
    scope: FieldScope
    default_requirement: Requirement = "optional"
    canonical_unit: str | None = None
    allowed_units: tuple[str, ...] = ()
    allowed_values: tuple[str, ...] = ()
    markets: tuple[str, ...] = ()
    locales: tuple[str, ...] = ()
    constraints: FieldConstraints = Field(default_factory=FieldConstraints)
    evidence: EvidenceRequirement = Field(default_factory=EvidenceRequirement)
    buyer_intents: tuple[str, ...] = ()
    mapping: StructuredDataMapping = Field(default_factory=StructuredDataMapping)
    human_verification_required: bool = False

    @model_validator(mode="after")
    def validate_field_contract(self) -> TaxonomyFieldDefinition:
        if self.data_type == "enum" and not self.allowed_values:
            raise ValueError(f"enum field {self.key!r} requires allowed_values")
        if (
            self.canonical_unit
            and self.allowed_units
            and self.canonical_unit not in self.allowed_units
        ):
            raise ValueError(
                f"canonical_unit for {self.key!r} must be included in allowed_units"
            )
        return self


class CategoryDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: CanonicalKey
    label: str = Field(min_length=1, max_length=200)
    parent_key: CanonicalKey | None = None
    assignable_primary: bool = True
    allow_secondary_tag: bool = True
    signals: tuple[str, ...] = ()
    requirements: dict[CanonicalKey, Requirement] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_assignable_category(self) -> CategoryDefinition:
        if self.assignable_primary and not self.signals:
            raise ValueError(f"assignable category {self.key!r} requires signals")
        return self


class TaxonomyPackage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"]
    vertical: CanonicalKey
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    status: Literal["published"]
    immutable: Literal[True]
    title: str = Field(min_length=1, max_length=250)
    fields: tuple[TaxonomyFieldDefinition, ...]
    categories: tuple[CategoryDefinition, ...]

    @model_validator(mode="after")
    def validate_references(self) -> TaxonomyPackage:
        field_keys = [field.key for field in self.fields]
        category_keys = [category.key for category in self.categories]
        if len(field_keys) != len(set(field_keys)):
            raise ValueError("taxonomy field keys must be unique")
        if len(category_keys) != len(set(category_keys)):
            raise ValueError("taxonomy category keys must be unique")

        known_fields = set(field_keys)
        known_categories = set(category_keys)
        for category in self.categories:
            if category.parent_key and category.parent_key not in known_categories:
                raise ValueError(
                    f"category {category.key!r} references unknown parent {category.parent_key!r}"
                )
            unknown_fields = set(category.requirements) - known_fields
            if unknown_fields:
                unknown = ", ".join(sorted(unknown_fields))
                raise ValueError(
                    f"category {category.key!r} references unknown fields: {unknown}"
                )

        parents = {category.key: category.parent_key for category in self.categories}
        for category_key in category_keys:
            seen: set[str] = set()
            current: str | None = category_key
            while current is not None:
                if current in seen:
                    raise ValueError(f"category inheritance cycle detected at {current!r}")
                seen.add(current)
                current = parents[current]

        if not any(category.assignable_primary for category in self.categories):
            raise ValueError("taxonomy must define at least one assignable category")
        return self
