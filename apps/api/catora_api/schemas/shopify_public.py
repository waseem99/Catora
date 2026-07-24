from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ShopifyStoreInvitationCreateRequest(BaseModel):
    shop_domain: str = Field(min_length=1, max_length=255)
    prospect_name: str = Field(min_length=1, max_length=200)
    expires_in_hours: int = Field(default=168, ge=1, le=720)
    feature_tier: Literal["demo", "plus_demo"] = "demo"


class ShopifyStoreInvitationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    activated_workspace_id: uuid.UUID | None
    shop_domain: str
    prospect_name: str
    feature_tier: Literal["demo", "plus_demo"]
    status: Literal["pending", "activated", "revoked", "expired"]
    expires_at: datetime
    activated_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ShopifyPublicSessionView(BaseModel):
    shop_domain: str
    shopify_user_id: str
    invitation_status: Literal["pending", "activated"]
    feature_tier: Literal["demo", "plus_demo"]
    invitation_expires_at: datetime
    activated_workspace_id: uuid.UUID | None
    session_expires_at: datetime


class ShopifyPublicActivationView(BaseModel):
    shop_domain: str
    workspace_id: uuid.UUID
    installation_id: uuid.UUID
    catalog_source_id: uuid.UUID
    ingestion_job_id: uuid.UUID | None = None
    invitation_status: Literal["activated"] = "activated"
    installation_status: Literal["active"] = "active"
    feature_tier: Literal["demo", "plus_demo"]
    sync_status: Literal[
        "not_started",
        "queued",
        "coalesced",
        "running",
        "completed",
        "failed",
    ]
    created: bool
