from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CategoryKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]


class TaxonomyCompileResponse(BaseModel):
    categories_created: int = Field(ge=0)
    fields_created: int = Field(ge=0)
    rule_definitions_created: int = Field(ge=0)
    rule_versions_created: int = Field(ge=0)
    taxonomy_version: str
    fingerprint: str = Field(min_length=64, max_length=64)


class CategorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    label: str
    taxonomy_version: str


class CategoryPreviewResponse(BaseModel):
    product_id: uuid.UUID
    taxonomy_version: str
    taxonomy_fingerprint: str = Field(min_length=64, max_length=64)
    classifier_version: str
    status: Literal["assigned", "ambiguous", "unclassified"]
    primary_category_key: str | None
    candidate_keys: list[str]
    secondary_tag_keys: list[str]
    scores: dict[str, int]


class AssignProductCategoriesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taxonomy_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    primary_category_key: CategoryKey
    secondary_category_keys: list[CategoryKey] = Field(default_factory=list, max_length=20)
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def validate_category_keys(self) -> AssignProductCategoriesRequest:
        if len(self.secondary_category_keys) != len(set(self.secondary_category_keys)):
            raise ValueError("secondary_category_keys must be unique")
        if self.primary_category_key in self.secondary_category_keys:
            raise ValueError("primary category cannot also be a secondary category")
        return self


class ProductCategoryAssignmentResponse(BaseModel):
    product_id: uuid.UUID
    taxonomy_version: str
    primary_category: CategorySummary
    secondary_categories: list[CategorySummary]
