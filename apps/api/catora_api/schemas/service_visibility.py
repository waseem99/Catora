# ruff: noqa: E501
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

SERVICE_VISIBILITY_PROTOCOL_VERSION = "2026-07-service-visibility-v1"
SERVICE_VISIBILITY_MAX_BATCH_PAGES = 100


def _validate_json_value(value: Any, *, depth: int = 0) -> None:
    if depth > 8:
        raise ValueError("Structured-data nesting cannot exceed 8 levels")
    if isinstance(value, dict):
        if len(value) > 500:
            raise ValueError("Structured-data objects cannot exceed 500 fields")
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 200:
                raise ValueError("Structured-data keys must be non-empty strings")
            _validate_json_value(item, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 500:
            raise ValueError("Structured-data arrays cannot exceed 500 items")
        for item in value:
            _validate_json_value(item, depth=depth + 1)
    elif isinstance(value, str) and len(value) > 20_000:
        raise ValueError("Structured-data strings cannot exceed 20000 characters")


class ServiceVisibilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ServicePageSnapshot(ServiceVisibilityModel):
    id: str = Field(min_length=1, max_length=500)
    url: HttpUrl
    canonical_url: HttpUrl = Field(alias="canonicalUrl")
    status_code: int = Field(alias="statusCode", ge=100, le=599)
    title: str = Field(default="", max_length=1_000)
    meta_description: str | None = Field(default=None, alias="metaDescription", max_length=5_000)
    h1: str | None = Field(default=None, max_length=2_000)
    headings: list[str] = Field(default_factory=list, max_length=500)
    visible_text: str = Field(alias="visibleText", max_length=250_000)
    internal_links: list[HttpUrl] = Field(default_factory=list, alias="internalLinks", max_length=5_000)
    structured_data: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="structuredData",
        max_length=200,
    )
    post_type: str | None = Field(default=None, alias="postType", max_length=100)
    author: str | None = Field(default=None, max_length=500)
    published_at: datetime | None = Field(default=None, alias="publishedAt")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    robots: list[str] = Field(default_factory=list, max_length=50)
    content_hash: str = Field(alias="contentHash", min_length=64, max_length=64)

    @model_validator(mode="after")
    def require_public_https_urls(self) -> Self:
        if self.url.scheme != "https" or self.canonical_url.scheme != "https":
            raise ValueError("Service visibility pages must use HTTPS")
        return self

    @field_validator("robots")
    @classmethod
    def normalize_robots(cls, value: list[str]) -> list[str]:
        return sorted({item.strip().casefold() for item in value if item.strip()})

    @field_validator("structured_data")
    @classmethod
    def validate_structured_data(
        cls,
        value: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        _validate_json_value(value)
        return value

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        normalized = value.casefold()
        if any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("contentHash must be a hexadecimal SHA-256 digest")
        return normalized


class ServiceVisibilitySourceCreateRequest(ServiceVisibilityModel):
    name: str = Field(min_length=2, max_length=200)
    start_url: HttpUrl = Field(alias="startUrl")
    connection_mode: Literal["zero_install", "wordpress_bridge"] = Field(
        default="zero_install",
        alias="connectionMode",
    )
    authorized_domain_confirmed: bool = Field(alias="authorizedDomainConfirmed")
    max_pages: int = Field(default=150, alias="maxPages", ge=1, le=250)

    @model_validator(mode="after")
    def require_authorization(self) -> Self:
        if not self.authorized_domain_confirmed:
            raise ValueError("Exact-domain authorization must be confirmed")
        if self.start_url.scheme != "https":
            raise ValueError("Service visibility sources must use HTTPS")
        return self


class ServiceVisibilitySourceProvisionResponse(ServiceVisibilityModel):
    source_id: uuid.UUID = Field(alias="sourceId")
    connection_mode: str = Field(alias="connectionMode")
    endpoint: HttpUrl | None = None
    token: str | None = Field(default=None, min_length=32)
    token_fingerprint: str | None = Field(default=None, alias="tokenFingerprint")
    protocol_version: str = Field(alias="protocolVersion")


class ServiceVisibilityRunResponse(ServiceVisibilityModel):
    source_id: uuid.UUID = Field(alias="sourceId")
    job_id: uuid.UUID = Field(alias="jobId")
    status: str


class ServiceVisibilityBridgeBatch(ServiceVisibilityModel):
    protocol_version: str = Field(alias="protocolVersion")
    snapshot_id: uuid.UUID = Field(alias="snapshotId")
    sequence: int = Field(ge=0)
    complete: bool = False
    pages: list[ServicePageSnapshot] = Field(
        min_length=1,
        max_length=SERVICE_VISIBILITY_MAX_BATCH_PAGES,
    )

    @field_validator("protocol_version")
    @classmethod
    def validate_protocol(cls, value: str) -> str:
        if value != SERVICE_VISIBILITY_PROTOCOL_VERSION:
            raise ValueError("Unsupported service visibility protocol version")
        return value

    @model_validator(mode="after")
    def reject_duplicate_pages(self) -> Self:
        canonicals = [str(page.canonical_url).rstrip("/") for page in self.pages]
        if len(canonicals) != len(set(canonicals)):
            raise ValueError("Snapshot batches cannot repeat a canonical page")
        return self


class ServiceVisibilityFindingView(ServiceVisibilityModel):
    rule_id: str = Field(alias="ruleId")
    rule_version: str = Field(alias="ruleVersion")
    severity: Literal["critical", "high", "medium", "low", "info"]
    category: str
    title: str
    url: HttpUrl | None = None
    evidence: str
    remediation: str


class ServiceVisibilityQuestionView(ServiceVisibilityModel):
    position: int
    question: str
    question_type: str = Field(alias="questionType")
    coverage_state: Literal[
        "supported",
        "partially_supported",
        "unsupported",
        "conflicting",
    ] = Field(alias="coverageState")
    score_basis_points: int = Field(alias="scoreBasisPoints")
    evidence: list[dict[str, object]] = Field(default_factory=list)
    explanation: str


class ServiceVisibilityScorecard(ServiceVisibilityModel):
    source_id: uuid.UUID = Field(alias="sourceId")
    job_id: uuid.UUID = Field(alias="jobId")
    page_count: int = Field(alias="pageCount", ge=0)
    score_basis_points: int = Field(alias="scoreBasisPoints", ge=0, le=10_000)
    component_scores: dict[str, int] = Field(alias="componentScores")
    findings: list[ServiceVisibilityFindingView]
    questions: list[ServiceVisibilityQuestionView]
    warnings: list[str] = Field(default_factory=list)


class ServiceVisibilityReportResponse(ServiceVisibilityModel):
    report_job_id: uuid.UUID = Field(alias="reportJobId")
    artifacts: list[dict[str, object]]
