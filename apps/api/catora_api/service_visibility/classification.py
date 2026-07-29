# ruff: noqa: E501
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from catora_api.schemas.service_visibility import ServicePageSnapshot

PageType = Literal[
    "home", "service", "industry", "case_study", "expert", "resource",
    "location", "about", "contact", "legal", "other",
]


@dataclass(frozen=True, slots=True)
class EntityDraft:
    entity_type: str
    key: str
    name: str
    relationship_type: str
    confidence: str
    evidence: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class ClassifiedPage:
    page_type: PageType
    confidence: str
    entities: tuple[EntityDraft, ...]


_PATH_HINTS: tuple[tuple[PageType, tuple[str, ...]], ...] = (
    ("case_study", ("case-study", "case-studies", "success-story", "portfolio", "work")),
    ("industry", ("industries", "industry", "sectors", "verticals")),
    ("service", ("services", "solutions", "capabilities", "consulting", "development")),
    ("expert", ("team", "leadership", "experts", "people", "authors")),
    ("location", ("locations", "offices", "regions", "countries")),
    ("resource", ("blog", "resources", "insights", "guides", "whitepapers", "news")),
    ("about", ("about", "company", "who-we-are")),
    ("contact", ("contact", "get-in-touch", "book-a-call")),
    ("legal", ("privacy", "terms", "cookies", "legal")),
)
_TECHNOLOGY_NAMES = (
    "aws", "azure", "google cloud", "kubernetes", "docker", "react", "next.js",
    "node.js", "wordpress", "shopify", "salesforce", "sap", "microsoft dynamics",
    "python", "java", ".net",
)
_INDUSTRY_NAMES = (
    "healthcare", "fintech", "financial services", "retail", "ecommerce",
    "manufacturing", "logistics", "education", "government", "real estate",
    "hospitality", "telecommunications",
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:200] or "unknown"


def _clean(value: str) -> str:
    return " ".join(value.split()).strip(" -|:")[:300]


def _page_type(page: ServicePageSnapshot) -> tuple[PageType, str]:
    path = urlparse(str(page.canonical_url)).path.strip("/").casefold()
    if not path:
        return "home", "high"
    segments = tuple(part for part in path.split("/") if part)
    post_type = (page.post_type or "").casefold()
    if post_type in {"case_study", "case-study", "portfolio"}:
        return "case_study", "high"
    if post_type in {"service", "services"}:
        return "service", "high"
    if post_type in {"team", "expert", "person"}:
        return "expert", "high"
    for page_type, hints in _PATH_HINTS:
        if any(hint in segments or hint in path for hint in hints):
            return page_type, "high"
    title = f"{page.title} {page.h1 or ''}".casefold()
    if any(token in title for token in ("service", "consulting", "development", "integration")):
        return "service", "medium"
    if "case study" in title or "success story" in title:
        return "case_study", "medium"
    return "other", "low"


def _entity(
    entity_type: str,
    name: str,
    relationship_type: str,
    page: ServicePageSnapshot,
    *,
    confidence: str,
    field: str,
) -> EntityDraft:
    cleaned = _clean(name)
    return EntityDraft(
        entity_type=entity_type,
        key=_slug(cleaned),
        name=cleaned,
        relationship_type=relationship_type,
        confidence=confidence,
        evidence=({"url": str(page.canonical_url), "field": field, "excerpt": cleaned},),
    )


def _extract_entities(page: ServicePageSnapshot, page_type: PageType) -> tuple[EntityDraft, ...]:
    entities: list[EntityDraft] = []
    primary = _clean(page.h1 or page.title)
    if page_type in {"service", "industry", "case_study", "expert"} and primary:
        entities.append(_entity(page_type, primary, "describes", page, confidence="high", field="h1"))
    searchable = f"{page.title}\n{page.h1 or ''}\n{page.visible_text}".casefold()
    for technology in _TECHNOLOGY_NAMES:
        if technology in searchable:
            entities.append(_entity("technology", technology, "uses", page, confidence="medium", field="visible_text"))
    for industry in _INDUSTRY_NAMES:
        if industry in searchable:
            entities.append(_entity("industry", industry, "serves", page, confidence="medium", field="visible_text"))
    for block in page.structured_data:
        type_value = block.get("@type")
        types = {type_value} if isinstance(type_value, str) else {
            item for item in type_value if isinstance(item, str)
        } if isinstance(type_value, list) else set()
        name = block.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        if types & {"Organization", "LocalBusiness", "Corporation"}:
            entities.append(_entity("company", name, "describes", page, confidence="high", field="structured_data"))
        if "Service" in types:
            entities.append(_entity("service", name, "describes", page, confidence="high", field="structured_data"))
        if "Person" in types:
            entities.append(_entity("expert", name, "authored_by", page, confidence="high", field="structured_data"))
    unique = {(item.entity_type, item.key, item.relationship_type): item for item in entities}
    return tuple(unique[key] for key in sorted(unique))


def classify_page(page: ServicePageSnapshot) -> ClassifiedPage:
    page_type, confidence = _page_type(page)
    return ClassifiedPage(page_type, confidence, _extract_entities(page, page_type))
