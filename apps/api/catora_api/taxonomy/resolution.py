from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from catora_api.taxonomy.schema import Requirement, TaxonomyPackage

_TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class ResolvedCategory:
    key: str
    label: str
    parent_chain: tuple[str, ...]
    assignable_primary: bool
    allow_secondary_tag: bool
    signals: tuple[str, ...]
    requirements: dict[str, Requirement]
    requirement_sources: dict[str, str]


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    status: Literal["assigned", "ambiguous", "unclassified"]
    primary_category_key: str | None
    candidate_keys: tuple[str, ...]
    secondary_tag_keys: tuple[str, ...]
    scores: dict[str, int]


def resolve_categories(package: TaxonomyPackage) -> dict[str, ResolvedCategory]:
    definitions = {category.key: category for category in package.categories}
    resolved: dict[str, ResolvedCategory] = {}

    def resolve(category_key: str) -> ResolvedCategory:
        cached = resolved.get(category_key)
        if cached is not None:
            return cached
        definition = definitions[category_key]
        requirements: dict[str, Requirement] = {
            field.key: field.default_requirement for field in package.fields
        }
        requirement_sources = {field.key: "field_default" for field in package.fields}
        parent_chain: tuple[str, ...] = ()
        if definition.parent_key is not None:
            parent = resolve(definition.parent_key)
            requirements.update(parent.requirements)
            requirement_sources.update(parent.requirement_sources)
            parent_chain = (*parent.parent_chain, parent.key)
        for field_key, requirement in definition.requirements.items():
            requirements[field_key] = requirement
            requirement_sources[field_key] = definition.key
        category = ResolvedCategory(
            key=definition.key,
            label=definition.label,
            parent_chain=parent_chain,
            assignable_primary=definition.assignable_primary,
            allow_secondary_tag=definition.allow_secondary_tag,
            signals=definition.signals,
            requirements=requirements,
            requirement_sources=requirement_sources,
        )
        resolved[category_key] = category
        return category

    for key in definitions:
        resolve(key)
    return resolved


def classify_product(
    package: TaxonomyPackage,
    *,
    title: str,
    category_text: str | None = None,
    description: str | None = None,
) -> ClassificationResult:
    resolved = resolve_categories(package)
    title_text = _search_text(title)
    category_search_text = _search_text(category_text or "")
    combined_text = " ".join(
        part for part in (title_text, category_search_text, _search_text(description or "")) if part
    )
    scores: dict[str, int] = {}
    for category in resolved.values():
        if not category.assignable_primary:
            continue
        score = 0
        for signal in category.signals:
            normalized_signal = _search_text(signal)
            if not normalized_signal:
                continue
            signal_score = max(2, len(normalized_signal.split()) * 2)
            if _contains_phrase(title_text, normalized_signal):
                score += signal_score + 3
            elif _contains_phrase(category_search_text, normalized_signal):
                score += signal_score + 2
            elif _contains_phrase(combined_text, normalized_signal):
                score += signal_score
        if score:
            scores[category.key] = score

    if not scores:
        return ClassificationResult(
            status="unclassified",
            primary_category_key=None,
            candidate_keys=(),
            secondary_tag_keys=(),
            scores={},
        )

    highest = max(scores.values())
    candidates = tuple(sorted(key for key, value in scores.items() if value == highest))
    if len(candidates) != 1:
        return ClassificationResult(
            status="ambiguous",
            primary_category_key=None,
            candidate_keys=candidates,
            secondary_tag_keys=(),
            scores=dict(sorted(scores.items())),
        )

    primary = candidates[0]
    secondary = tuple(
        key
        for key, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if key != primary and resolved[key].allow_secondary_tag and score > 0
    )
    return ClassificationResult(
        status="assigned",
        primary_category_key=primary,
        candidate_keys=(primary,),
        secondary_tag_keys=secondary,
        scores=dict(sorted(scores.items())),
    )


def _search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return _TOKEN_PATTERN.sub(" ", normalized.casefold()).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    if not text or not phrase:
        return False
    return f" {phrase} " in f" {text} "
