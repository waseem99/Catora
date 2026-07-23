from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

InstallationStatus = Literal[
    "pending",
    "active",
    "refresh_required",
    "disconnected",
    "revoked",
    "failed",
]
TokenMode = Literal["expiring_offline", "non_expiring_offline"]
InstallationHealth = Literal[
    "healthy",
    "refresh_required",
    "disconnected",
    "unknown",
]
SyncStatus = Literal[
    "not_started",
    "queued",
    "coalesced",
    "running",
    "completed",
    "failed",
    "revoked",
]
ShopifyWebhookTopic = Literal[
    "app/uninstalled",
    "products/create",
    "products/update",
    "products/delete",
]
ShopifyWebhookStatus = Literal["queued", "completed", "ignored", "failed"]


class ShopifyInstallationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ShopifyInstallStartRequest(ShopifyInstallationModel):
    shop_domain: str = Field(min_length=18, max_length=255)

    @field_validator("shop_domain")
    @classmethod
    def normalize_shop_domain(cls, value: str) -> str:
        from catora_api.shopify.installations import normalize_shop_domain

        return normalize_shop_domain(value)


class ShopifyInstallStartResponse(ShopifyInstallationModel):
    authorization_url: str
    expires_at: datetime


class ShopifyWebhookDeliveryView(ShopifyInstallationModel):
    id: uuid.UUID
    topic: ShopifyWebhookTopic
    status: ShopifyWebhookStatus
    signature_verified: bool = True
    received_at: datetime
    processed_at: datetime | None = None
    product_id: str | None = None
    ingestion_job_id: uuid.UUID | None = None


class ShopifyInstallationView(ShopifyInstallationModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    catalog_source_id: uuid.UUID | None = None
    shop_domain: str
    status: InstallationStatus
    granted_scopes: list[str]
    token_mode: TokenMode
    access_token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    installed_at: datetime | None = None
    refreshed_at: datetime | None = None
    disconnected_at: datetime | None = None
    last_health_checked_at: datetime | None = None
    health: InstallationHealth
    detail: str
    sync_status: SyncStatus = "not_started"
    last_successful_sync_at: datetime | None = None
    last_sync_job_id: uuid.UUID | None = None
    last_audit_run_id: uuid.UUID | None = None
    product_count: int = 0
    variant_count: int = 0
    warning_count: int = 0
    last_sync_error_type: str | None = None
    latest_webhook: ShopifyWebhookDeliveryView | None = None


class ShopifyConfigurationView(ShopifyInstallationModel):
    enabled: bool
    required_scopes: list[str]
    callback_url: str | None = None


class ShopifyWebhookResponse(ShopifyInstallationModel):
    accepted: bool = True
    duplicate: bool
    delivery_id: uuid.UUID
