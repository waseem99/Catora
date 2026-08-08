from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FindingSeverity = Literal["critical", "high", "medium", "low", "informational"]
FindingLifecycle = Literal["new", "persisting"]
QuestionStatus = Literal["supported", "partially_supported", "unsupported", "conflicting"]
PageType = Literal[
    "home",
    "service",
    "industry",
    "location",
    "case_study",
    "expert",
    "about",
    "contact",
    "faq",
    "generic",
]


class ServiceVisibilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageEvidence(ServiceVisibilityModel):
    url: str
    canonical_url: str
    title: str = ""
    meta_description: str = ""
    robots: str = ""
    headings: list[dict[str, str]] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    visible_text: str = ""
    json_ld: list[dict[str, object]] = Field(default_factory=list)
    wordpress: dict[str, object] = Field(default_factory=dict)
    page_type: PageType = "generic"
    content_hash: str
    source_updated_at: datetime | None = None


class ServiceEntity(ServiceVisibilityModel):
    kind: Literal[
        "company",
        "service",
        "industry",
        "audience",
        "problem",
        "outcome",
        "technology",
        "location",
        "case_study",
        "expert",
    ]
    name: str
    page_url: str
    confidence: Literal["high", "medium", "low"] = "medium"
    evidence_excerpt: str = ""


class ServiceFinding(ServiceVisibilityModel):
    fingerprint: str
    code: str
    family: Literal["technical_seo", "aeo", "ai_discovery", "architecture"]
    severity: FindingSeverity
    lifecycle: FindingLifecycle = "new"
    title: str
    detail: str
    recommendation: str
    page_url: str | None = None
    evidence: list[dict[str, str]] = Field(default_factory=list)


class BuyerQuestionResult(ServiceVisibilityModel):
    key: str
    question: str
    status: QuestionStatus
    rationale: str
    evidence: list[dict[str, str]] = Field(default_factory=list)


class ServiceSiteModel(ServiceVisibilityModel):
    company_name: str
    site_url: str
    pages: list[PageEvidence]
    entities: list[ServiceEntity]
    service_names: list[str]
    industry_names: list[str]
    location_names: list[str]
    evidence_page_count: int


class ServiceVisibilityScorecard(ServiceVisibilityModel):
    overall: int = Field(ge=0, le=100)
    technical_seo: int = Field(ge=0, le=100)
    aeo: int = Field(ge=0, le=100)
    ai_discovery: int = Field(ge=0, le=100)
    architecture: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)


class ServiceVisibilityContinuity(ServiceVisibilityModel):
    new_findings: int = 0
    persisting_findings: int = 0
    resolved_findings: int = 0
    new_pages: list[str] = Field(default_factory=list)
    changed_pages: list[str] = Field(default_factory=list)
    removed_pages: list[str] = Field(default_factory=list)
    unchanged_page_count: int = 0
    prior_report_id: str | None = None


class ServiceVisibilityReport(ServiceVisibilityModel):
    version: Literal["service-visibility/v1"] = "service-visibility/v1"
    generated_at: datetime
    source_id: str
    ingestion_job_id: str
    site: ServiceSiteModel
    scorecard: ServiceVisibilityScorecard
    findings: list[ServiceFinding]
    buyer_questions: list[BuyerQuestionResult]
    continuity: ServiceVisibilityContinuity
    executive_summary: list[str]
    disclaimers: list[str] = Field(
        default_factory=lambda: [
            (
                "Catora does not guarantee rankings, traffic, leads, revenue, "
                "AI citations, or rich results."
            ),
            (
                "Generated recommendations are evidence-backed proposals and require "
                "human review before publication."
            ),
        ]
    )
