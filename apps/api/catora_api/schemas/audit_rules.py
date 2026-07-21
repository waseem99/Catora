from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from catora_api.schemas.audits import Severity

CanonicalKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
CustomRuleKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,99}$")]
RelationshipOperator = Literal[
    "less_than_or_equal_to_field",
    "greater_than_or_equal_to_field",
    "matches_product_field",
]


class CustomAuditRuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: CustomRuleKey
    name: str = Field(min_length=3, max_length=250)
    description: str = Field(min_length=3, max_length=2000)
    taxonomy_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    category_key: CanonicalKey
    field_key: CanonicalKey
    relationship: RelationshipOperator
    related_field_key: CanonicalKey
    severity: Severity = "medium"

    @model_validator(mode="after")
    def validate_relationship(self) -> CustomAuditRuleCreateRequest:
        if (
            self.relationship
            in {
                "less_than_or_equal_to_field",
                "greater_than_or_equal_to_field",
            }
            and self.field_key == self.related_field_key
        ):
            raise ValueError("numeric relationships cannot reference their own field")
        return self


class CustomAuditRuleView(BaseModel):
    rule_definition_id: uuid.UUID
    rule_version_id: uuid.UUID
    workspace_id: uuid.UUID
    key: str
    name: str
    description: str
    taxonomy_version: str
    category_key: str
    field_key: str
    relationship: RelationshipOperator
    related_field_key: str
    severity: Severity
    is_immutable: bool
