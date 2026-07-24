from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ShopifyPublicSyncStatus = Literal[
    "not_started",
    "queued",
    "coalesced",
    "running",
    "completed",
    "failed",
]
ShopifyPublicInstallationStatus = Literal[
    "active",
    "refresh_required",
    "disconnected",
    "failed",
]
ShopifyBulkOperationStatus = Literal[
    "canceled",
    "canceling",
    "completed",
    "failed",
]
ShopifyAnalysisStatus = Literal[
    "not_started",
    "running",
    "completed",
    "failed",
]


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
    sync_status: ShopifyPublicSyncStatus
    created: bool


class ShopifyPublicInstallationView(BaseModel):
    shop_domain: str
    workspace_id: uuid.UUID
    installation_id: uuid.UUID
    catalog_source_id: uuid.UUID | None = None
    feature_tier: Literal["demo", "plus_demo"]
    installation_status: ShopifyPublicInstallationStatus
    sync_status: ShopifyPublicSyncStatus
    product_count: int = Field(default=0, ge=0)
    variant_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    assigned_category_count: int = Field(default=0, ge=0)
    ambiguous_category_count: int = Field(default=0, ge=0)
    unclassified_category_count: int = Field(default=0, ge=0)
    last_successful_sync_at: datetime | None = None
    last_sync_job_id: uuid.UUID | None = None
    last_audit_run_id: uuid.UUID | None = None
    last_sync_error_type: str | None = None
    last_sync_full_reconciliation: bool = False
    last_completed_full_reconciliation: bool = False
    last_bulk_operation_status: ShopifyBulkOperationStatus | None = None
    last_bulk_operation_completed_at: datetime | None = None
    last_bulk_webhook_received_at: datetime | None = None
    last_bulk_operation_error_code: str | None = None
    analysis_status: ShopifyAnalysisStatus = "not_started"
    analysis_stale: bool = False
    analysis_completed_at: datetime | None = None
    analysis_error_type: str | None = None
    finding_count: int = Field(default=0, ge=0)
    intent_run_count: int = Field(default=0, ge=0)
    intent_match_count: int = Field(default=0, ge=0)
    confident_match_count: int = Field(default=0, ge=0)
    possible_match_missing_data_count: int = Field(default=0, ge=0)
    report_ready: bool = False
    report_path: str | None = None
    backlog_path: str | None = None
    reauthorization_required: bool = False
