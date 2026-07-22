from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IdentityProductSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    canonical_key: str
    title: str
    status: str


class IdentitySignal(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    value: str | None = Field(default=None, max_length=500)
    weight_basis_points: int = Field(ge=0, le=10000)


class ProductIdentityCandidateView(BaseModel):
    id: uuid.UUID
    left_product: IdentityProductSummary
    right_product: IdentityProductSummary
    match_type: Literal["deterministic", "fuzzy"]
    score_basis_points: int = Field(ge=0, le=10000)
    signals: list[IdentitySignal]
    algorithm_version: str
    status: Literal["pending", "accepted", "rejected", "superseded"]
    resolved_by_user_id: uuid.UUID | None
    resolved_at: datetime | None
    resolution_reason: str | None
    created_at: datetime
    updated_at: datetime


class ProductIdentityCandidateListResponse(BaseModel):
    items: list[ProductIdentityCandidateView]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)


class IdentityCandidateRefreshResponse(BaseModel):
    products_considered: int = Field(ge=0)
    candidates_created: int = Field(ge=0)
    candidates_updated: int = Field(ge=0)
    candidates_superseded: int = Field(ge=0)
    truncated: bool
    algorithm_version: str


class LinkProductsRequest(BaseModel):
    target_product_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=1000)
    candidate_id: uuid.UUID | None = None


class UnlinkProductRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class RejectIdentityCandidateRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class ProductIdentityMemberView(BaseModel):
    product: IdentityProductSummary
    linked_by_user_id: uuid.UUID | None
    link_reason: str
    linked_at: datetime


class ProductIdentityView(BaseModel):
    identity_id: uuid.UUID
    status: Literal["active", "dissolved"]
    members: list[ProductIdentityMemberView]
    created_at: datetime
    updated_at: datetime


class UnlinkProductResponse(BaseModel):
    identity_id: uuid.UUID
    product_id: uuid.UUID
    dissolved: bool
