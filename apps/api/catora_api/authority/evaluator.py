from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit

from catora_api.authority.models import (
    AuthorityObservation,
    AuthorityOpportunity,
    OpportunityType,
    RiskState,
)

_PROHIBITED_PATTERNS = (
    "buy backlinks",
    "paid link",
    "link farm",
    "private blog network",
    "pbn",
    "guaranteed ranking",
    "guaranteed traffic",
)
_HIGH_RISK_HOST_PARTS = ("linkfarm", "backlink-market", "paid-links", "pbn")


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def normalize_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Authority URLs must be absolute HTTP(S) URLs")
    host = parsed.hostname.casefold().removeprefix("www.")
    path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/") or "/"
    return f"{parsed.scheme.casefold()}://{host}{path}"


def observation_risk(observation: AuthorityObservation) -> RiskState:
    normalize_url(observation.source_url)
    normalize_url(observation.target_url)
    haystack = " ".join(
        value
        for value in (
            observation.source_title or "",
            observation.anchor_or_mention_text or "",
            observation.source_url,
        )
    ).casefold()
    host = (urlsplit(observation.source_url).hostname or "").casefold()
    if any(pattern in haystack for pattern in _PROHIBITED_PATTERNS):
        return "prohibited"
    if any(part in host for part in _HIGH_RISK_HOST_PARTS):
        return "prohibited"
    if observation.sponsored is True:
        return "review_required"
    if observation.identity_state in {"ambiguous", "unmatched"}:
        return "review_required"
    return "allowed"


def derive_opportunity(
    observation: AuthorityObservation,
) -> AuthorityOpportunity | None:
    risk = observation_risk(observation)
    if risk == "prohibited":
        return None
    if observation.identity_state in {"ambiguous", "unmatched"}:
        return AuthorityOpportunity(
            opportunity_type="citation_correction",
            state="suppressed",
            risk_state="review_required",
            title="Resolve ambiguous authority observation identity",
            rationale=(
                "The observation cannot be assigned confidently to a restaurant brand "
                "or location, so no outreach or correction should proceed."
            ),
            verification_method="A human reviewer resolves the entity and confirms the URLs.",
            owner_role="brand_data_owner",
            evidence_hashes=(observation.observation_hash,),
            score_basis_points=0,
        )
    opportunity_type: OpportunityType
    title: str
    rationale: str
    verification: str
    score: int
    owner = "pr_owner"
    if observation.observation_type == "local_citation":
        opportunity_type = "citation_correction"
        title = "Review local citation consistency"
        rationale = (
            "A dated local citation observation is available for an identified restaurant entity. "
            "The listing should be checked against approved name, address, phone and URL facts."
        )
        verification = "Re-observe the citation and compare approved identity fields."
        score = 8_000
        owner = "local_visibility_owner"
    elif observation.link_state in {"lost", "broken"}:
        opportunity_type = "link_reclamation"
        title = "Review a lost or broken authority link"
        rationale = (
            "A previously relevant link appears lost or broken. Any reclamation must be "
            "relationship-based and manually approved."
        )
        verification = "Confirm the source page and target URL resolve after the approved action."
        score = 7_500
    elif observation.observation_type == "unlinked_mention":
        opportunity_type = "relationship_outreach"
        title = "Review an unlinked brand mention"
        rationale = (
            "A permitted source mentions the identified restaurant without a link. This is a "
            "relationship opportunity, not an entitlement to placement."
        )
        verification = "Confirm the mention remains factual and any resulting link is live."
        score = 6_500
    elif observation.observation_type == "media_opportunity":
        opportunity_type = "expert_commentary"
        title = "Review an evidence-backed media opportunity"
        rationale = (
            "A dated media opportunity may align with approved restaurant expertise. Claims and "
            "contact use require brand and legal review."
        )
        verification = "Record the reviewer decision and any independently published outcome."
        score = 6_000
    else:
        opportunity_type = "relationship_outreach"
        title = "Review a current authority relationship"
        rationale = (
            "A current identified observation may support a legitimate relationship or community "
            "opportunity after manual review."
        )
        verification = "Confirm the source, relationship and public outcome manually."
        score = 5_000
    if risk == "review_required":
        score = min(score, 4_000)
    return AuthorityOpportunity(
        opportunity_type=opportunity_type,
        risk_state=risk,
        title=title,
        rationale=rationale,
        verification_method=verification,
        owner_role=owner,
        evidence_hashes=(observation.observation_hash,),
        score_basis_points=score,
    )


def reconcile_authority_batch(
    observations: tuple[AuthorityObservation, ...],
) -> dict[str, int]:
    seen: set[tuple[str, str]] = set()
    counts = {
        "received": len(observations),
        "unique": 0,
        "duplicate": 0,
        "matched": 0,
        "ambiguous": 0,
        "unmatched": 0,
        "prohibited": 0,
        "opportunities": 0,
    }
    for observation in observations:
        key = (observation.external_observation_id, observation.observation_hash)
        if key in seen:
            counts["duplicate"] += 1
            continue
        seen.add(key)
        counts["unique"] += 1
        if observation.identity_state in {"exact", "alias"}:
            counts["matched"] += 1
        elif observation.identity_state == "ambiguous":
            counts["ambiguous"] += 1
        else:
            counts["unmatched"] += 1
        if observation_risk(observation) == "prohibited":
            counts["prohibited"] += 1
        elif derive_opportunity(observation) is not None:
            counts["opportunities"] += 1
    return counts
