# ruff: noqa: E501

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from catora_api.service_visibility.models import (
    BuyerQuestionResult,
    PageEvidence,
    ServiceEntity,
    ServiceFinding,
    ServiceSiteModel,
    ServiceVisibilityContinuity,
    ServiceVisibilityReport,
    ServiceVisibilityScorecard,
)

QUESTION_TEMPLATES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("service_definition", "What does the company provide?", ("service", "solution", "we provide", "we help")),
    ("ideal_customer", "Who is each service designed for?", ("for teams", "for companies", "for businesses", "ideal for", "who we help")),
    ("problems_solved", "Which customer problems does the service solve?", ("problem", "challenge", "pain", "solve", "reduce")),
    ("business_outcomes", "Which business outcomes can customers expect?", ("outcome", "result", "improve", "increase", "reduce", "save")),
    ("delivery_process", "What is the delivery process?", ("process", "approach", "how it works", "discovery", "implementation")),
    ("timeline", "How long does delivery usually take?", ("week", "month", "timeline", "duration", "delivery time")),
    ("pricing", "How is the service priced?", ("price", "pricing", "cost", "quote", "engagement")),
    ("scope", "What is included and excluded?", ("included", "scope", "deliverable", "excludes", "not included")),
    ("technologies", "Which technologies and platforms are supported?", ("technology", "platform", "stack", "aws", "azure", "google cloud", "wordpress")),
    ("industries", "Which industries does the company serve?", ("industry", "industries", "sector", "vertical")),
    ("locations", "Which locations and markets are served?", ("location", "market", "country", "global", "remote")),
    ("case_studies", "What evidence shows the company has delivered this service?", ("case study", "customer story", "client", "project", "results")),
    ("expertise", "Who are the subject-matter experts?", ("expert", "team", "author", "founder", "consultant")),
    ("credentials", "Which certifications or partnerships support credibility?", ("certified", "certification", "partner", "accredited", "award")),
    ("differentiation", "How is the company different from alternatives?", ("different", "why choose", "advantage", "unique", "unlike")),
    ("comparison", "How does the service compare with common alternatives?", ("compare", "versus", "vs.", "alternative", "in-house")),
    ("risks", "What risks or limitations should buyers understand?", ("risk", "limitation", "depends", "constraint", "trade-off")),
    ("security", "How are security and privacy handled?", ("security", "privacy", "data protection", "gdpr", "compliance")),
    ("support", "What support is available after delivery?", ("support", "maintenance", "retainer", "after launch", "managed")),
    ("onboarding", "What information is needed to begin?", ("get started", "onboarding", "requirements", "access", "kickoff")),
    ("measurement", "How is success measured?", ("measure", "metric", "kpi", "success", "reporting")),
    ("faq", "Are common buyer questions answered directly?", ("frequently asked", "faq", "questions", "answers")),
    ("contact", "Is there a clear next step for a qualified buyer?", ("contact", "book", "schedule", "consultation", "talk to")),
    ("ownership", "Who owns the work and the resulting assets?", ("ownership", "intellectual property", "ip", "handover", "source code")),
    ("change_management", "How are revisions and change requests handled?", ("revision", "change request", "feedback", "iteration", "approval")),
)

_PAGE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("case_study", ("case-study", "case-studies", "customer-story", "portfolio", "our-work")),
    ("industry", ("industry", "industries", "sectors", "verticals")),
    ("location", ("locations", "location", "areas-we-serve", "near-me")),
    ("expert", ("team", "people", "experts", "authors", "leadership")),
    ("about", ("about", "company", "who-we-are")),
    ("contact", ("contact", "book", "consultation", "get-started")),
    ("faq", ("faq", "frequently-asked")),
    ("service", ("service", "services", "solutions", "consulting", "development", "design", "marketing")),
)


def _clean(value: object, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _page_type(url: str, title: str, headings: list[dict[str, str]]) -> str:
    path = urlparse(url).path.casefold().strip("/")
    if not path:
        return "home"
    haystack = " ".join((path.replace("-", " "), title.casefold(), " ".join(item.get("text", "").casefold() for item in headings)))
    for page_type, terms in _PAGE_PATTERNS:
        if any(term in haystack for term in terms):
            return page_type
    return "generic"


def _json_ld_types(values: list[dict[str, object]]) -> set[str]:
    result: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        type_value = value.get("@type")
        if isinstance(type_value, str):
            result.add(type_value.casefold())
        elif isinstance(type_value, list):
            result.update(str(item).casefold() for item in type_value if isinstance(item, str))
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in value:
                visit(value[key])

    visit(values)
    return result


def _excerpt(text: str, term: str = "", limit: int = 240) -> str:
    compact = " ".join(text.split())
    if not compact:
        return ""
    if term:
        index = compact.casefold().find(term.casefold())
        if index >= 0:
            start = max(0, index - 70)
            return compact[start : start + limit]
    return compact[:limit]


def _fingerprint(code: str, page_url: str | None, detail: str) -> str:
    stable = "\n".join((code, page_url or "site", detail.casefold().strip()))
    return hashlib.sha256(stable.encode()).hexdigest()


def _finding(
    *,
    code: str,
    family: str,
    severity: str,
    title: str,
    detail: str,
    recommendation: str,
    page: PageEvidence | None = None,
    evidence_text: str = "",
) -> ServiceFinding:
    page_url = page.url if page is not None else None
    evidence: list[dict[str, str]] = []
    if page is not None:
        evidence.append({"url": page.url, "excerpt": evidence_text or _excerpt(page.visible_text)})
    return ServiceFinding(
        fingerprint=_fingerprint(code, page_url, detail),
        code=code,
        family=family,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        title=title,
        detail=detail,
        recommendation=recommendation,
        page_url=page_url,
        evidence=evidence,
    )


def _company_name(pages: list[PageEvidence], site_url: str) -> str:
    for page in pages:
        for block in page.json_ld:
            graph = block.get("@graph") if isinstance(block, dict) else None
            candidates = graph if isinstance(graph, list) else [block]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                type_value = candidate.get("@type")
                types = {type_value.casefold()} if isinstance(type_value, str) else {
                    item.casefold() for item in type_value if isinstance(item, str)
                } if isinstance(type_value, list) else set()
                if types & {"organization", "localbusiness", "corporation", "professionalservice"}:
                    name = _clean(candidate.get("name"), 200)
                    if name:
                        return name
    home = next((page for page in pages if page.page_type == "home"), None)
    if home and home.title:
        return re.split(r"[|–—-]", home.title, maxsplit=1)[0].strip()[:200]
    return (urlparse(site_url).hostname or "Service company").removeprefix("www.")


def _entities(pages: list[PageEvidence], company_name: str) -> list[ServiceEntity]:
    result = [
        ServiceEntity(
            kind="company",
            name=company_name,
            page_url=pages[0].url if pages else "",
            confidence="high",
            evidence_excerpt=company_name,
        )
    ]
    seen = {("company", company_name.casefold())}
    page_kind = {
        "service": "service",
        "industry": "industry",
        "location": "location",
        "case_study": "case_study",
        "expert": "expert",
    }
    for page in pages:
        kind = page_kind.get(page.page_type)
        if kind is None:
            continue
        h1 = next((item.get("text", "") for item in page.headings if item.get("level") == "h1"), "")
        name = _clean(h1 or page.title, 200)
        if not name:
            continue
        key = (kind, name.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(
            ServiceEntity(
                kind=kind,  # type: ignore[arg-type]
                name=name,
                page_url=page.url,
                confidence="high" if h1 else "medium",
                evidence_excerpt=_excerpt(page.visible_text),
            )
        )
    return result


def _duplicate_findings(pages: list[PageEvidence], attribute: str, code: str) -> list[ServiceFinding]:
    groups: dict[str, list[PageEvidence]] = defaultdict(list)
    for page in pages:
        value = getattr(page, attribute).casefold().strip()
        if value:
            groups[value].append(page)
    findings: list[ServiceFinding] = []
    for duplicate_pages in groups.values():
        if len(duplicate_pages) < 2:
            continue
        urls = ", ".join(page.url for page in duplicate_pages[:4])
        for page in duplicate_pages:
            findings.append(
                _finding(
                    code=code,
                    family="technical_seo",
                    severity="medium",
                    title=f"Duplicate {attribute.replace('_', ' ')}",
                    detail=f"The same {attribute.replace('_', ' ')} appears on {len(duplicate_pages)} pages: {urls}",
                    recommendation=f"Write a unique {attribute.replace('_', ' ')} that reflects this page's specific service, audience, or evidence.",
                    page=page,
                    evidence_text=getattr(page, attribute),
                )
            )
    return findings


def _audit(pages: list[PageEvidence], entities: list[ServiceEntity]) -> list[ServiceFinding]:
    findings: list[ServiceFinding] = []
    for page in pages:
        h1s = [item for item in page.headings if item.get("level") == "h1" and item.get("text")]
        types = _json_ld_types(page.json_ld)
        text = page.visible_text.casefold()
        if not page.title:
            findings.append(_finding(code="seo.missing_title", family="technical_seo", severity="high", title="Missing page title", detail="The page does not expose a usable HTML title.", recommendation="Add a concise, unique title describing the page's service, audience, or purpose.", page=page))
        elif len(page.title) < 20 or len(page.title) > 65:
            findings.append(_finding(code="seo.title_length", family="technical_seo", severity="low", title="Title length is weak", detail=f"The title contains {len(page.title)} characters.", recommendation="Keep the title specific and usually between 20 and 65 characters without keyword stuffing.", page=page, evidence_text=page.title))
        if not page.meta_description:
            findings.append(_finding(code="seo.missing_description", family="technical_seo", severity="medium", title="Missing meta description", detail="The page does not provide a meta description.", recommendation="Add a factual description that summarizes the service and intended buyer.", page=page))
        if not page.canonical_url:
            findings.append(_finding(code="seo.missing_canonical", family="technical_seo", severity="medium", title="Missing canonical URL", detail="No canonical link was detected.", recommendation="Add a self-referencing canonical URL for this indexable page.", page=page))
        if "noindex" in page.robots.casefold():
            findings.append(_finding(code="seo.noindex", family="technical_seo", severity="high", title="Page is marked noindex", detail="The robots meta directive contains noindex.", recommendation="Confirm this is intentional; otherwise remove the noindex directive before relying on the page for discovery.", page=page, evidence_text=page.robots))
        if not h1s:
            findings.append(_finding(code="seo.missing_h1", family="technical_seo", severity="medium", title="Missing primary heading", detail="No visible H1 heading was detected.", recommendation="Add one clear H1 that names the service, topic, or page purpose.", page=page))
        elif len(h1s) > 1:
            findings.append(_finding(code="seo.multiple_h1", family="technical_seo", severity="low", title="Multiple primary headings", detail=f"The page exposes {len(h1s)} H1 headings.", recommendation="Use one primary H1 and structure supporting sections with H2/H3 headings.", page=page, evidence_text=" | ".join(item["text"] for item in h1s)))
        if len(page.visible_text.split()) < 180 and page.page_type in {"home", "service", "industry", "location"}:
            findings.append(_finding(code="content.thin", family="aeo", severity="medium", title="Page provides limited answer depth", detail=f"Only {len(page.visible_text.split())} visible words were retained for analysis.", recommendation="Add specific definitions, suitability, process, evidence, constraints, and next steps rather than generic filler.", page=page))
        opening = " ".join(page.visible_text.split()[:80]).casefold()
        if page.page_type == "service" and not any(term in opening for term in ("we help", "service", "provides", "designed for", "enables")):
            findings.append(_finding(code="aeo.weak_opening_answer", family="aeo", severity="high", title="Service is not defined early", detail="The opening passage does not clearly state what the service is, who it serves, and the outcome it supports.", recommendation="Add a short direct-answer paragraph near the beginning using verified company facts.", page=page, evidence_text=_excerpt(page.visible_text)))
        if page.page_type == "service" and not any(term in text for term in ("process", "approach", "how it works", "steps")):
            findings.append(_finding(code="aeo.missing_process", family="aeo", severity="medium", title="Delivery process is unclear", detail="No clear process or approach language was detected on the service page.", recommendation="Describe the delivery stages, buyer inputs, decision points, and handoff.", page=page))
        if page.page_type == "service" and not any(term in text for term in ("case study", "client", "customer", "result", "project")):
            findings.append(_finding(code="geo.missing_evidence", family="ai_discovery", severity="high", title="Service claims lack page-level evidence", detail="The service page does not connect its claims to a case study, named project, measurable result, or verifiable proof.", recommendation="Link verified case studies, examples, credentials, or named expertise to the relevant service claims.", page=page))
        if page.page_type == "service" and not (types & {"service", "professionalservice"}):
            findings.append(_finding(code="schema.missing_service", family="ai_discovery", severity="medium", title="Service structured data is absent", detail="No Service or ProfessionalService JSON-LD type was detected.", recommendation="Add validated Service JSON-LD based only on visible, verified page facts.", page=page))
        if page.page_type == "case_study" and not any(char.isdigit() for char in page.visible_text):
            findings.append(_finding(code="geo.case_study_no_specifics", family="ai_discovery", severity="medium", title="Case study lacks specific evidence", detail="The page contains no numeric detail that could substantiate scope, timing, or outcomes.", recommendation="Add verified dates, scale, deliverables, or outcome measurements where the customer permits disclosure.", page=page))
    findings.extend(_duplicate_findings(pages, "title", "seo.duplicate_title"))
    findings.extend(_duplicate_findings(pages, "meta_description", "seo.duplicate_description"))

    page_types = Counter(page.page_type for page in pages)
    entity_types = Counter(entity.kind for entity in entities)
    if not page_types["service"]:
        findings.append(_finding(code="architecture.no_service_pages", family="architecture", severity="critical", title="No dedicated service pages found", detail="The crawl did not identify any dedicated service page.", recommendation="Create one evidence-backed page per commercially meaningful service rather than relying only on a generic home page."))
    if not page_types["case_study"]:
        findings.append(_finding(code="architecture.no_case_studies", family="architecture", severity="high", title="No case-study evidence found", detail="The site does not expose a dedicated case-study or customer-story page.", recommendation="Publish approved case studies that connect a problem, delivery work, evidence, and outcome."))
    if not page_types["contact"]:
        findings.append(_finding(code="architecture.no_contact_path", family="architecture", severity="high", title="No clear conversion path found", detail="The crawl did not identify a dedicated contact, booking, or consultation page.", recommendation="Provide a clear next step and link it from relevant service pages."))
    if not page_types["expert"]:
        findings.append(_finding(code="geo.no_experts", family="ai_discovery", severity="medium", title="Named expertise is difficult to verify", detail="The site does not expose a team, expert, author, or leadership page.", recommendation="Publish verified expert profiles with roles, experience, and relevant service ownership."))
    if entity_types["service"] and not entity_types["industry"]:
        findings.append(_finding(code="architecture.no_industry_context", family="architecture", severity="low", title="Services are not connected to industries", detail="Service entities were found, but no dedicated industry context was identified.", recommendation="Add industry context only where the company has genuine experience and evidence."))
    return findings


def _questions(pages: list[PageEvidence]) -> list[BuyerQuestionResult]:
    results: list[BuyerQuestionResult] = []
    for key, question, terms in QUESTION_TEMPLATES:
        matches: list[tuple[PageEvidence, str]] = []
        negated = False
        for page in pages:
            text = page.visible_text.casefold()
            for term in terms:
                if term in text:
                    matches.append((page, term))
                    window = _excerpt(page.visible_text, term).casefold()
                    if any(prefix in window for prefix in ("not available", "do not", "does not", "cannot", "no support")):
                        negated = True
                    break
        evidence = [
            {"url": page.url, "excerpt": _excerpt(page.visible_text, term)}
            for page, term in matches[:3]
        ]
        if not matches:
            status = "unsupported"
            rationale = "No direct public-page evidence was found for this buyer question."
        elif negated and len(matches) > 1:
            status = "conflicting"
            rationale = "The site contains potentially conflicting statements that require human review."
        elif len(matches) == 1:
            status = "partially_supported"
            rationale = "One relevant passage was found, but coverage is limited or isolated."
        else:
            status = "supported"
            rationale = f"Relevant evidence was found across {len(matches)} pages."
        results.append(BuyerQuestionResult(key=key, question=question, status=status, rationale=rationale, evidence=evidence))  # type: ignore[arg-type]
    return results


def _score(findings: list[ServiceFinding], pages: list[PageEvidence]) -> ServiceVisibilityScorecard:
    weights = {"critical": 24, "high": 12, "medium": 6, "low": 2, "informational": 0}
    families = ("technical_seo", "aeo", "ai_discovery", "architecture")
    scores: dict[str, int] = {}
    for family in families:
        penalty = sum(weights[finding.severity] for finding in findings if finding.family == family)
        scores[family] = max(0, 100 - min(100, penalty))
    confidence = min(100, 35 + len(pages) * 4 + sum(1 for page in pages if page.json_ld) * 2)
    overall = round(sum(scores.values()) / len(scores))
    return ServiceVisibilityScorecard(
        overall=overall,
        technical_seo=scores["technical_seo"],
        aeo=scores["aeo"],
        ai_discovery=scores["ai_discovery"],
        architecture=scores["architecture"],
        confidence=confidence,
    )


def _page_from_payload(payload: dict[str, Any], content_hash: str, source_updated_at: datetime | None) -> PageEvidence:
    headings = [
        {"level": _clean(item.get("level"), 10).casefold(), "text": _clean(item.get("text"), 500)}
        for item in payload.get("headings", [])
        if isinstance(item, dict)
    ]
    json_ld = [item for item in payload.get("json_ld", []) if isinstance(item, dict)]
    url = _clean(payload.get("source_url") or payload.get("url"), 2000)
    canonical = _clean(payload.get("canonical_url") or url, 2000)
    title = _clean(payload.get("title"), 500)
    return PageEvidence(
        url=url,
        canonical_url=canonical,
        title=title,
        meta_description=_clean(payload.get("meta_description"), 1000),
        robots=_clean(payload.get("robots"), 200),
        headings=headings,
        links=[_clean(item, 2000) for item in payload.get("links", []) if isinstance(item, str)],
        visible_text=_clean(payload.get("visible_text"), 50_000),
        json_ld=json_ld,
        wordpress=dict(payload.get("wordpress") or {}) if isinstance(payload.get("wordpress"), dict) else {},
        page_type=_page_type(url, title, headings),  # type: ignore[arg-type]
        content_hash=content_hash,
        source_updated_at=source_updated_at,
    )


def analyze_service_site(
    *,
    source_id: str,
    ingestion_job_id: str,
    site_url: str,
    records: list[tuple[dict[str, Any], str, datetime | None]],
    prior_report_id: str | None = None,
    prior_fingerprints: set[str] | None = None,
) -> ServiceVisibilityReport:
    pages = sorted(
        (_page_from_payload(payload, content_hash, source_updated_at) for payload, content_hash, source_updated_at in records),
        key=lambda page: page.url,
    )
    company_name = _company_name(pages, site_url)
    entities = _entities(pages, company_name)
    findings = _audit(pages, entities)
    prior = prior_fingerprints or set()
    current = {finding.fingerprint for finding in findings}
    for finding in findings:
        finding.lifecycle = "persisting" if finding.fingerprint in prior else "new"
    questions = _questions(pages)
    scorecard = _score(findings, pages)
    continuity = ServiceVisibilityContinuity(
        new_findings=sum(finding.lifecycle == "new" for finding in findings),
        persisting_findings=sum(finding.lifecycle == "persisting" for finding in findings),
        resolved_findings=len(prior - current),
        prior_report_id=prior_report_id,
    )
    site = ServiceSiteModel(
        company_name=company_name,
        site_url=site_url,
        pages=pages,
        entities=entities,
        service_names=sorted({entity.name for entity in entities if entity.kind == "service"}),
        industry_names=sorted({entity.name for entity in entities if entity.kind == "industry"}),
        location_names=sorted({entity.name for entity in entities if entity.kind == "location"}),
        evidence_page_count=len(pages),
    )
    unsupported = sum(item.status == "unsupported" for item in questions)
    top_findings = sorted(findings, key=lambda finding: ({"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}[finding.severity], finding.title))[:3]
    summary = [
        f"Catora analyzed {len(pages)} authorized public pages and identified {len(site.service_names)} service entities.",
        f"The evidence-backed visibility score is {scorecard.overall}/100; confidence is {scorecard.confidence}/100.",
        f"{unsupported} of {len(questions)} common buyer questions lack direct public-page support.",
    ]
    summary.extend(f"Priority: {finding.title}." for finding in top_findings)
    return ServiceVisibilityReport(
        generated_at=datetime.now(UTC),
        source_id=source_id,
        ingestion_job_id=ingestion_job_id,
        site=site,
        scorecard=scorecard,
        findings=sorted(findings, key=lambda finding: (finding.family, finding.severity, finding.page_url or "", finding.code)),
        buyer_questions=questions,
        continuity=continuity,
        executive_summary=summary,
    )
