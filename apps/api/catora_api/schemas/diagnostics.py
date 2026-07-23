from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DiagnosticStatus = Literal[
    "awaiting_upload",
    "queued",
    "ingesting",
    "normalizing",
    "categorizing",
    "auditing",
    "matching",
    "preparing_reports",
    "completed",
    "failed",
    "deleting",
]


class DiagnosticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class DiagnosticCreateRequest(DiagnosticModel):
    company_name: str = Field(min_length=2, max_length=200)
    market_code: str = Field(min_length=2, max_length=35, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    locale: str = Field(min_length=2, max_length=35, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    retention_days: int = Field(default=30, ge=1, le=90)
    authorization_confirmed: bool
    storefront_domain: str | None = Field(default=None, min_length=3, max_length=255)

    @field_validator("company_name")
    @classmethod
    def normalize_company_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("market_code", "currency")
    @classmethod
    def uppercase_codes(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("locale")
    @classmethod
    def normalize_locale(cls, value: str) -> str:
        parts = value.strip().split("-")
        return "-".join([parts[0].lower(), *[part.upper() for part in parts[1:]]])

    @field_validator("storefront_domain")
    @classmethod
    def normalize_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
        if "/" in normalized or " " in normalized or "." not in normalized:
            raise ValueError("storefront_domain must be a hostname")
        return normalized

    @model_validator(mode="after")
    def require_authorization(self) -> DiagnosticCreateRequest:
        if not self.authorization_confirmed:
            raise ValueError("Catalog authorization must be confirmed")
        return self


class DiagnosticCounts(DiagnosticModel):
    processed_rows: int = 0
    accepted_rows: int = 0
    rejected_rows: int = 0
    warning_count: int = 0
    product_count: int = 0
    variant_count: int = 0
    assigned_category_count: int = 0
    ambiguous_category_count: int = 0
    unclassified_category_count: int = 0
    finding_count: int = 0
    intent_run_count: int = 0
    intent_match_count: int = 0


class DiagnosticView(DiagnosticModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    organization_id: uuid.UUID
    company_name: str
    status: DiagnosticStatus
    current_stage: str
    detail: str
    market_code: str
    locale: str
    currency: str
    retention_expires_at: datetime
    counts: DiagnosticCounts
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    ingestion_job_id: uuid.UUID | None = None
    audit_run_id: uuid.UUID | None = None
    intent_run_ids: list[uuid.UUID] = Field(default_factory=list)
    result_path: str
    report_path: str
    backlog_path: str
    rejection_path: str


class DiagnosticRejection(DiagnosticModel):
    row_number: int = Field(ge=1)
    reason: str
    product_handle: str | None = None
    variant_sku: str | None = None


class DiagnosticRejectionList(DiagnosticModel):
    items: list[DiagnosticRejection]
    total_rejected: int
    sample_limit: int
