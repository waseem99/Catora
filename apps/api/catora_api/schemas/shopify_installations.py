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


class ShopifyInstallationView(ShopifyInstallationModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    catalog_source_id: uuid.UUID | None = None
    shop_domain: str
    status: InstallationStatus
    granted_scopes: list[str]
    token_mode: Literal["expiring_offline", "non_expiring_offline"]
    access_token_expires_at: datetime | None = None
    refresh_token_expires_at: datetime | None = None
    installed_at: datetime | None = None
    refreshed_at: datetime | None = None
    disconnected_at: datetime | None = None
    last_health_checked_at: datetime | None = None
    health: Literal["healthy", "refresh_required", "disconnected", "unknown"]
    detail: str


class ShopifyConfigurationView(ShopifyInstallationModel):
    enabled: bool
    required_scopes: list[str]
    callback_url: str | None = None
