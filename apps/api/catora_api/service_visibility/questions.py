# ruff: noqa: E501
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
    for page in pages:
        if classify_page(page).page_type != "service":
            continue
        name = " ".join((page.h1 or page.title).split()).strip(" -|:")
        if name and name.casefold() not in {item.casefold() for item in names}:
            names.append(name)
    return tuple(names[:1])


def build_default_questions(pages: Iterable[ServicePageSnapshot]) -> tuple[QuestionDefinition, ...]:
    page_tuple = tuple(pages)
    services = _service_names(page_tuple) or ("the company's primary service",)
    questions: list[QuestionDefinition] = []
    templates = (
        ("definition", "What does {service} include?", ("include", "scope", "service")),
        ("fit", "Who is {service} best suited for?", ("for", "team", "company", "organization")),
        ("problem", "Which business problems does {service} solve?", ("problem", "challenge", "solve", "pain")),
        ("outcome", "What outcomes can clients expect from {service}?", ("outcome", "result", "benefit", "improve")),
        ("process", "How is {service} delivered?", ("process", "approach", "method", "steps")),
    )
    for service in services:
        key = re.sub(r"[^a-z0-9]+", "-", service.casefold()).strip("-")[:200]
        for question_type, template, terms in templates:
            questions.append(_definition(len(questions) + 1, template.format(service=service), question_type, key, terms))
    generic = (
        ("timing", "How long do typical engagements take?", ("week", "month", "timeline", "duration")),
        ("cost", "What factors affect the cost of an engagement?", ("cost", "pricing", "budget", "estimate")),
        ("proof", "What public evidence demonstrates delivery experience?", ("case study", "client", "project", "result")),
        ("expertise", "Who provides the service and what expertise do they have?", ("team", "expert", "experience", "certified")),
        ("industry", "Which industries does the company serve?", ("industry", "sector", "vertical")),
        ("technology", "Which technologies and platforms are supported?", ("technology", "platform", "stack", "cloud")),
        ("location", "Which locations or markets can the company support?", ("location", "office", "country", "global")),
        ("comparison", "How does the approach compare with alternatives?", ("versus", "compared", "alternative", "difference")),
        ("risk", "What risks, limitations or prerequisites are disclosed?", ("risk", "limitation", "requirement", "prerequisite")),
        ("next_step", "What is the next step for a qualified buyer?", ("contact", "book", "consultation", "call")),
        ("security", "How does the company address security and privacy?", ("security", "privacy", "protection", "compliance")),
        ("onboarding", "What does client onboarding involve?", ("onboarding", "kickoff", "discovery", "workshop")),
        ("support", "What support is available after delivery?", ("support", "maintenance", "managed", "ongoing")),
        ("ownership", "Who owns deliverables and intellectual property?", ("ownership", "intellectual property", "ip", "deliverable")),
        ("scalability", "Can the service scale as client requirements grow?", ("scale", "scalable", "growth", "capacity")),
        ("integration", "Which existing systems can the service integrate with?", ("integrate", "integration", "api", "existing systems")),
        ("data", "What client data or access is required?", ("data", "access", "credentials", "inputs")),
        ("governance", "How are delivery decisions and changes governed?", ("governance", "approval", "review", "change control")),
        ("measurement", "How is project success measured?", ("measure", "metric", "kpi", "success")),
        ("limitations", "What is explicitly outside the service scope?", ("not included", "out of scope", "exclusion", "limitation")),
    )
    for question_type, question, terms in generic:
        if len(questions) >= 25:
            break
        questions.append(_definition(len(questions) + 1, question, question_type, None, terms))
    return tuple(questions[:25])


def _evidence(page: ServicePageSnapshot, terms: tuple[str, ...]) -> dict[str, object] | None:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", page.visible_text):
        cleaned = " ".join(sentence.split())
        if len(cleaned) >= 20 and any(term in cleaned.casefold() for term in terms):
            return {"pageId": page.id, "url": str(page.canonical_url), "excerpt": cleaned[:1000]}
    return None


def evaluate_questions(
    pages: Iterable[ServicePageSnapshot],
    questions: Iterable[QuestionDefinition],
) -> tuple[QuestionEvaluation, ...]:
    page_tuple = tuple(sorted(pages, key=lambda page: (str(page.canonical_url), page.id)))
    results: list[QuestionEvaluation] = []
    for question in questions:
        matches_list: list[dict[str, object]] = []
        for group in question.required_terms:
            for page in page_tuple:
                found = _evidence(page, group)
                if found is not None:
                    matches_list.append(found)
                    break
        matches = tuple(matches_list)
        ratio = len(matches) / max(1, len(question.required_terms))
        state = "supported" if ratio == 1 else "partially_supported" if ratio else "unsupported"
        score = 10_000 if state == "supported" else 5_000 if state == "partially_supported" else 0
        explanation = {
            "supported": "The site contains public evidence covering the required answer dimensions.",
            "partially_supported": "The site contains some relevant evidence but does not cover the full question.",
            "unsupported": "No sufficient public-page evidence was found for this question.",
        }[state]
        results.append(QuestionEvaluation(question, state, score, matches, (), explanation))
    return tuple(results)
