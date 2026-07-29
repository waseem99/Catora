# ruff: noqa: E501
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from catora_api.schemas.service_visibility import ServicePageSnapshot
from catora_api.service_visibility.classification import classify_page


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    rule_version: str
    severity: str
    category: str
    title: str
    url: str | None
    evidence: str
    remediation: str


def _finding(
    rule_id: str,
    severity: str,
    category: str,
    title: str,
    page: ServicePageSnapshot | None,
    evidence: str,
    remediation: str,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rule_version="2026-07-v1",
        severity=severity,
        category=category,
        title=title,
        url=str(page.canonical_url) if page else None,
        evidence=evidence[:2_000],
        remediation=remediation,
    )


def evaluate_rules(pages: Iterable[ServicePageSnapshot]) -> tuple[Finding, ...]:
    page_tuple = tuple(pages)
    findings: list[Finding] = []
    service_pages = [page for page in page_tuple if classify_page(page).page_type == "service"]
    for page in page_tuple:
        if "noindex" in page.robots:
            findings.append(_finding("technical.noindex", "high", "technical", "Public page is marked noindex", page, "robots=noindex", "Remove noindex only when the page is intended for public discovery."))
        if not page.title.strip():
            findings.append(_finding("technical.missing_title", "high", "technical", "Page title is missing", page, "No title element was extracted.", "Add a unique, factual title describing the page."))
        elif len(page.title.strip()) < 20:
            findings.append(_finding("technical.short_title", "low", "technical", "Page title is unusually short", page, page.title, "Use a descriptive title without keyword stuffing."))
        if not page.meta_description:
            findings.append(_finding("technical.missing_description", "medium", "technical", "Meta description is missing", page, "No meta description was extracted.", "Add a concise description that matches visible page content."))
        if not page.h1:
            findings.append(_finding("structure.missing_h1", "medium", "structure", "Primary heading is missing", page, "No H1 was extracted.", "Add one clear primary heading."))
        if str(page.url).rstrip("/") != str(page.canonical_url).rstrip("/"):
            findings.append(_finding("technical.canonical_difference", "info", "technical", "Canonical differs from fetched URL", page, f"Fetched {page.url}; canonical {page.canonical_url}", "Verify the canonical is intentional and resolves within the authorized host."))
        classification = classify_page(page)
        if classification.page_type == "service":
            text = page.visible_text.casefold()
            if not any(term in text for term in ("process", "approach", "how we work", "method")):
                findings.append(_finding("answer.missing_process", "medium", "answer", "Service delivery process is unclear", page, "No clear process language was found.", "Add a factual delivery process or engagement sequence."))
            if not any(term in text for term in ("result", "outcome", "case study", "client", "project")):
                findings.append(_finding("evidence.missing_proof", "high", "evidence", "Service page lacks public proof", page, "No outcome, case-study or project evidence was found.", "Link to verified case studies, outcomes or representative work."))
            if not any(term in text for term in ("contact", "book", "call", "consultation", "get started")):
                findings.append(_finding("buyer.missing_next_step", "medium", "buyer", "Qualified buyer next step is unclear", page, "No clear next-step language was found.", "Provide one specific, non-misleading next action."))
        if classification.page_type == "resource" and not page.author:
            findings.append(_finding("trust.missing_author", "low", "trust", "Resource lacks visible authorship", page, "No author was extracted.", "Show a real author or accountable editorial owner."))
    if not service_pages:
        findings.append(_finding("entity.no_service_pages", "critical", "entity", "No clear service page was discovered", None, "The crawl did not classify any page as a service page.", "Create or clarify dedicated pages for the company's primary services."))
    organization_names = {
        str(block.get("name")).strip()
        for page in page_tuple
        for block in page.structured_data
        if isinstance(block, dict)
        and block.get("@type") in {"Organization", "Corporation", "LocalBusiness"}
        and isinstance(block.get("name"), str)
        and str(block.get("name")).strip()
    }
    if len(organization_names) > 1:
        findings.append(_finding("entity.organization_conflict", "high", "entity", "Organization names conflict across pages", None, ", ".join(sorted(organization_names)), "Use one verified organization identity in visible content and structured data."))
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    return tuple(
        sorted(
            findings,
            key=lambda item: (severity_order[item.severity], item.rule_id, item.url or ""),
        )
    )
