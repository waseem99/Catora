from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ConnectionMode = Literal["zero_install", "wordpress_bridge"]


def _public_https_origin(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Service website URLs must use HTTPS")
    if parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("Service website URLs cannot contain credentials or ports")
    if parsed.query or parsed.fragment:
        raise ValueError("Service website URLs cannot contain a query or fragment")
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    return urlunparse(("https", host, parsed.path.rstrip("/") or "", "", "", ""))


class ServiceVisibilitySchema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ServiceVisibilitySourceCreateRequest(ServiceVisibilitySchema):
    name: str = Field(min_length=2, max_length=200)
    site_url: str = Field(max_length=2000)
    connection_mode: ConnectionMode = "zero_install"
    authorized_domain_confirmed: Literal[True]
    max_pages: int = Field(default=250, ge=1, le=1000)
    max_sitemaps: int = Field(default=20, ge=1, le=50)
    crawl_delay_seconds: float = Field(default=0.5, ge=0, le=60)
    monitoring_enabled: bool = False

    @field_validator("site_url")
    @classmethod
    def normalize_site_url(cls, value: str) -> str:
        return _public_https_origin(value)


class ServiceVisibilitySourceView(ServiceVisibilitySchema):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    site_url: str
    connection_mode: ConnectionMode
    status: str
    monitoring_enabled: bool
    token_fingerprint: str | None = None
    created_at: datetime
    updated_at: datetime


class ServiceVisibilitySourceProvisionResponse(ServiceVisibilitySourceView):
    endpoint: str
    token: str | None = None


class ServiceVisibilityRunView(ServiceVisibilitySchema):
    id: uuid.UUID
    workspace_id: uuid.UUID
    source_id: uuid.UUID
    ingestion_job_id: uuid.UUID
    status: str
    scorecard: dict[str, int] = Field(default_factory=dict)
    page_count: int = 0
    finding_count: int = 0
    question_count: int = 0
    continuity: dict[str, object] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class WordPressPageRecord(ServiceVisibilitySchema):
    url: str = Field(max_length=2000)
    canonical_url: str | None = Field(default=None, max_length=2000)
    title: str = Field(default="", max_length=500)
    meta_description: str = Field(default="", max_length=1000)
    robots: str = Field(default="", max_length=200)
    headings: list[dict[str, str]] = Field(default_factory=list, max_length=200)
    links: list[str] = Field(default_factory=list, max_length=2000)
    visible_text: str = Field(default="", max_length=50_000)
    json_ld: list[dict[str, object]] = Field(default_factory=list, max_length=100)
    wordpress: dict[str, object] = Field(default_factory=dict)
    source_updated_at: datetime | None = None

    @field_validator("url", "canonical_url")
    @classmethod
    def normalize_page_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value.strip())
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ValueError("WordPress page URLs must use HTTPS")
        if parsed.username or parsed.password or parsed.port is not None:
            raise ValueError("WordPress page URLs cannot contain credentials or ports")
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        return urlunparse(("https", host, parsed.path or "/", "", parsed.query, ""))


class WordPressSnapshotManifest(ServiceVisibilitySchema):
    snapshot_id: uuid.UUID
    page_count: int = Field(ge=0, le=10_000)
    started_at: datetime
    site_url: str
    plugin_version: str = Field(min_length=1, max_length=50)

    @field_validator("site_url")
    @classmethod
    def normalize_site_url(cls, value: str) -> str:
        return _public_https_origin(value)

    @field_validator("started_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")
        return value


class WordPressSnapshotBatch(ServiceVisibilitySchema):
    snapshot_id: uuid.UUID
    sequence: int = Field(ge=0, le=100_000)
    records: list[WordPressPageRecord] = Field(max_length=100)


class WordPressSnapshotCompleteRequest(ServiceVisibilitySchema):
    snapshot_id: uuid.UUID
    batch_count: int = Field(ge=0, le=100_000)
    page_count: int = Field(ge=0, le=10_000)


class WordPressSnapshotStatus(ServiceVisibilitySchema):
    source_id: uuid.UUID
    snapshot_id: uuid.UUID
    status: str
    accepted_batches: int = 0
    accepted_pages: int = 0
    ingestion_job_id: uuid.UUID | None = None
    report_id: uuid.UUID | None = None


class DraftProposalCreateRequest(ServiceVisibilitySchema):
    page_url: str = Field(max_length=2000)
    wordpress_post_id: int = Field(gt=0)
    base_revision: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, max_length=100_000)
    meta_title: str | None = Field(default=None, max_length=500)
    meta_description: str | None = Field(default=None, max_length=1000)
    structured_data: dict[str, object] | None = None
    internal_links: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not any(
            (
                self.title,
                self.content,
                self.meta_title,
                self.meta_description,
                self.structured_data,
                self.internal_links,
            )
        ):
            raise ValueError("Draft proposal must contain at least one proposed change")
        return self


class DraftProposalView(ServiceVisibilitySchema):
    id: uuid.UUID
    source_id: uuid.UUID
    report_id: uuid.UUID
    status: str
    page_url: str
    wordpress_post_id: int
    base_revision: str
    proposal: dict[str, object]
    approved_at: datetime | None = None
    remote_draft_id: int | None = None
    error: str | None = None


class DraftResultRequest(ServiceVisibilitySchema):
    status: Literal["applied", "stale", "failed"]
    remote_draft_id: int | None = Field(default=None, gt=0)
    error: str | None = Field(default=None, max_length=1000)
