from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from catora_api.schemas.service_visibility import ServicePageSnapshot
from catora_api.service_visibility.classification import classify_page


@dataclass(frozen=True, slots=True)
class QuestionDefinition:
    position: int
    question: str
    question_type: str
    entity_key: str | None
    required_terms: tuple[tuple[str, ...], ...]
    question_hash: str


@dataclass(frozen=True, slots=True)
class QuestionEvaluation:
    question: QuestionDefinition
    coverage_state: str
    score_basis_points: int
    supporting_evidence: tuple[dict[str, object], ...]
    conflicting_evidence: tuple[dict[str, object], ...]
    explanation: str


def _definition(
    position: int,
    question: str,
    question_type: str,
    entity_key: str | None,
    *groups: tuple[str, ...],
) -> QuestionDefinition:
    digest = hashlib.sha256(
        "\n".join((question_type, entity_key or "", question.strip())).encode()
    ).hexdigest()
    return QuestionDefinition(position, question, question_type, entity_key, groups, digest)


def _service_names(pages: Iterable[ServicePageSnapshot]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for page in pages:
        if classify_page(page).page_type != "service":
            continue
        name = " ".join((page.h1 or page.title).split()).strip(" -|:")
        normalized = name.casefold()
        if name and normalized not in seen:
            seen.add(normalized)
            names.append(name)
    return tuple(names[:1])


def build_default_questions(pages: Iterable[ServicePageSnapshot]) -> tuple[QuestionDefinition, ...]:
    page_tuple = tuple(pages)
    services = _service_names(page_tuple) or ("the company's primary service",)
    questions: list[QuestionDefinition] = []
    templates: tuple[
        tuple[str, str, tuple[str, ...], tuple[str, ...]], ...
    ] = (
        (
            "definition",
            "What does {service} include?",
            ("include", "scope", "deliverable"),
            ("service", "engagement", "offering"),
        ),
        (
            "fit",
            "Who is {service} best suited for?",
            ("suited", "ideal", "designed for", "for teams"),
            ("company", "organization", "business", "team"),
        ),
        (
            "problem",
            "Which business problems does {service} solve?",
            ("problem", "challenge", "pain"),
            ("solve", "address", "reduce", "improve"),
        ),
        (
            "outcome",
            "What outcomes can clients expect from {service}?",
            ("outcome", "result", "benefit"),
            ("increase", "reduce", "improve", "enable"),
        ),
        (
            "process",
            "How is {service} delivered?",
            ("process", "approach", "method", "steps"),
            ("discovery", "delivery", "implementation", "review"),
        ),
    )
    for service in services:
        key = re.sub(r"[^a-z0-9]+", "-", service.casefold()).strip("-")[:200]
        for question_type, template, first_group, second_group in templates:
            questions.append(
                _definition(
                    len(questions) + 1,
                    template.format(service=service),
                    question_type,
                    key,
                    first_group,
                    second_group,
                )
            )
    generic: tuple[
        tuple[str, str, tuple[str, ...], tuple[str, ...]], ...
    ] = (
        (
            "timing",
            "How long do typical engagements take?",
            ("week", "month", "timeline", "duration"),
            ("phase", "milestone", "schedule", "delivery"),
        ),
        (
            "cost",
            "What factors affect the cost of an engagement?",
            ("cost", "pricing", "budget", "estimate"),
            ("scope", "complexity", "team", "duration"),
        ),
        (
            "proof",
            "What public evidence demonstrates delivery experience?",
            ("case study", "client", "project"),
            ("result", "outcome", "delivered", "testimonial"),
        ),
        (
            "expertise",
            "Who provides the service and what expertise do they have?",
            ("team", "expert", "consultant", "engineer"),
            ("experience", "certified", "specialist", "years"),
        ),
        (
            "industry",
            "Which industries does the company serve?",
            ("industry", "sector", "vertical"),
            ("healthcare", "finance", "retail", "manufacturing", "technology"),
        ),
        (
            "technology",
            "Which technologies and platforms are supported?",
            ("technology", "platform", "stack", "cloud"),
            ("aws", "azure", "react", "node", "wordpress", "shopify"),
        ),
        (
            "location",
            "Which locations or markets can the company support?",
            ("location", "office", "country", "market"),
            ("global", "remote", "region", "international"),
        ),
        (
            "comparison",
            "How does the approach compare with alternatives?",
            ("versus", "compared", "alternative", "difference"),
            ("advantage", "trade-off", "suitable", "choose"),
        ),
        (
            "risk",
            "What risks, limitations or prerequisites are disclosed?",
            ("risk", "limitation", "requirement", "prerequisite"),
            ("depends", "constraint", "assumption", "responsibility"),
        ),
        (
            "next_step",
            "What is the next step for a qualified buyer?",
            ("contact", "book", "consultation", "call"),
            ("start", "discuss", "assessment", "request"),
        ),
        (
            "security",
            "How does the company address security and privacy?",
            ("security", "privacy", "protection", "compliance"),
            ("access", "encryption", "policy", "control"),
        ),
        (
            "onboarding",
            "What does client onboarding involve?",
            ("onboarding", "kickoff", "discovery", "workshop"),
            ("access", "stakeholder", "requirements", "plan"),
        ),
        (
            "support",
            "What support is available after delivery?",
            ("support", "maintenance", "managed", "ongoing"),
            ("monitoring", "response", "retainer", "handover"),
        ),
        (
            "ownership",
            "Who owns deliverables and intellectual property?",
            ("ownership", "intellectual property", "copyright", "ip"),
            ("deliverable", "source code", "license", "transfer"),
        ),
        (
            "scalability",
            "Can the service scale as client requirements grow?",
            ("scale", "scalable", "growth", "capacity"),
            ("performance", "volume", "users", "demand"),
        ),
        (
            "integration",
            "Which existing systems can the service integrate with?",
            ("integrate", "integration", "api", "connector"),
            ("existing system", "platform", "data", "workflow"),
        ),
        (
            "data",
            "What client data or access is required?",
            ("data", "access", "credentials", "inputs"),
            ("permission", "environment", "account", "document"),
        ),
        (
            "governance",
            "How are delivery decisions and changes governed?",
            ("governance", "approval", "review", "change control"),
            ("decision", "stakeholder", "sign-off", "scope"),
        ),
        (
            "measurement",
            "How is project success measured?",
            ("measure", "metric", "kpi", "success"),
            ("baseline", "target", "report", "outcome"),
        ),
        (
            "limitations",
            "What is explicitly outside the service scope?",
            ("not included", "out of scope", "exclusion", "limitation"),
            ("responsibility", "assumption", "separate", "additional"),
        ),
    )
    for question_type, question, first_group, second_group in generic:
        if len(questions) >= 25:
            break
        questions.append(
            _definition(
                len(questions) + 1,
                question,
                question_type,
                None,
                first_group,
                second_group,
            )
        )
    return tuple(questions[:25])


def _sentences(page: ServicePageSnapshot) -> tuple[str, ...]:
    return tuple(
        cleaned
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", page.visible_text)
        if len(cleaned := " ".join(sentence.split())) >= 20
    )


def _is_negated(sentence: str, terms: tuple[str, ...]) -> bool:
    lowered = sentence.casefold()
    if not any(term in lowered for term in terms):
        return False
    negations = (
        "not included",
        "not available",
        "not supported",
        "does not include",
        "do not include",
        "doesn't include",
        "no support",
        "no guarantee",
        "without support",
        "outside the scope",
        "out of scope",
    )
    return any(marker in lowered for marker in negations)


def _evidence(
    page: ServicePageSnapshot,
    terms: tuple[str, ...],
    *,
    negated: bool,
) -> dict[str, object] | None:
    for sentence in _sentences(page):
        lowered = sentence.casefold()
        if not any(term in lowered for term in terms):
            continue
        if _is_negated(sentence, terms) != negated:
            continue
        return {
            "pageId": page.id,
            "url": str(page.canonical_url),
            "excerpt": sentence[:1000],
        }
    return None


def evaluate_questions(
    pages: Iterable[ServicePageSnapshot],
    questions: Iterable[QuestionDefinition],
) -> tuple[QuestionEvaluation, ...]:
    page_tuple = tuple(sorted(pages, key=lambda page: (str(page.canonical_url), page.id)))
    results: list[QuestionEvaluation] = []
    for question in questions:
        matches_list: list[dict[str, object]] = []
        conflicts_list: list[dict[str, object]] = []
        for group in question.required_terms:
            for page in page_tuple:
                found = _evidence(page, group, negated=False)
                if found is not None:
                    matches_list.append(found)
                    break
            for page in page_tuple:
                conflicting = _evidence(page, group, negated=True)
                if conflicting is not None:
                    conflicts_list.append(conflicting)
                    break
        matches = tuple(matches_list)
        conflicts = tuple(conflicts_list)
        ratio = len(matches) / max(1, len(question.required_terms))
        if matches and conflicts:
            state = "conflicting"
            score = 2_500
            explanation = (
                "The site contains both supporting and contradictory public evidence for this question."
            )
        elif ratio == 1:
            state = "supported"
            score = 10_000
            explanation = (
                "The site contains public evidence covering the required answer dimensions."
            )
        elif ratio > 0:
            state = "partially_supported"
            score = 5_000
            explanation = (
                "The site contains some relevant evidence but does not cover the full question."
            )
        else:
            state = "unsupported"
            score = 0
            explanation = "No sufficient public-page evidence was found for this question."
        results.append(
            QuestionEvaluation(
                question,
                state,
                score,
                matches,
                conflicts,
                explanation,
            )
        )
    return tuple(results)
