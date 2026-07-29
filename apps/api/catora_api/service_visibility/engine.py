# ruff: noqa: E501
from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable

from catora_api.schemas.service_visibility import (
    ServicePageSnapshot,
    ServiceVisibilityScorecard,
)
from catora_api.service_visibility.questions import build_default_questions, evaluate_questions
from catora_api.service_visibility.rules import evaluate_rules

_SEVERITY_PENALTY = {"critical": 2_500, "high": 1_200, "medium": 600, "low": 250, "info": 0}
_COMPONENTS = ("technical", "structure", "entity", "answer", "evidence", "buyer", "trust")


def build_scorecard(
    source_id: uuid.UUID,
    job_id: uuid.UUID,
    pages: Iterable[ServicePageSnapshot],
) -> ServiceVisibilityScorecard:
    page_tuple = tuple(pages)
    findings = evaluate_rules(page_tuple)
    questions = evaluate_questions(page_tuple, build_default_questions(page_tuple))
    deductions: dict[str, int] = defaultdict(int)
    for finding in findings:
        deductions[finding.category] += _SEVERITY_PENALTY[finding.severity]
    components = {
        component: max(0, 10_000 - deductions.get(component, 0))
        for component in _COMPONENTS
    }
    question_score = sum(item.score_basis_points for item in questions) // max(1, len(questions))
    components["buyer_questions"] = question_score
    score = sum(components.values()) // len(components)
    return ServiceVisibilityScorecard.model_validate(
        {
            "sourceId": source_id,
            "jobId": job_id,
            "pageCount": len(page_tuple),
            "scoreBasisPoints": score,
            "componentScores": components,
            "findings": [
                {
                    "ruleId": item.rule_id,
                    "ruleVersion": item.rule_version,
                    "severity": item.severity,
                    "category": item.category,
                    "title": item.title,
                    "url": item.url,
                    "evidence": item.evidence,
                    "remediation": item.remediation,
                }
                for item in findings
            ],
            "questions": [
                {
                    "position": item.question.position,
                    "question": item.question.question,
                    "questionType": item.question.question_type,
                    "coverageState": item.coverage_state,
                    "scoreBasisPoints": item.score_basis_points,
                    "evidence": [*item.supporting_evidence, *item.conflicting_evidence],
                    "explanation": item.explanation,
                }
                for item in questions
            ],
            "warnings": [] if page_tuple else [
                "No public pages were available for evaluation."
            ],
        }
    )
