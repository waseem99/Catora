from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


ROLE_CAPABILITIES: dict[Role, frozenset[str]] = {
    Role.OWNER: frozenset(
        {
            "organization.manage",
            "members.manage",
            "sources.write",
            "catalog.identity.manage",
            "catalog.taxonomy.manage",
            "analysis.run",
            "recommendations.write",
            "recommendations.review",
            "reports.write",
        }
    ),
    Role.ADMIN: frozenset(
        {
            "members.manage",
            "sources.write",
            "catalog.identity.manage",
            "catalog.taxonomy.manage",
            "analysis.run",
            "recommendations.write",
            "recommendations.review",
            "reports.write",
        }
    ),
    Role.ANALYST: frozenset({"analysis.run", "recommendations.write", "reports.write"}),
    Role.REVIEWER: frozenset({"recommendations.review"}),
    Role.VIEWER: frozenset(),
}


def can(role: Role | str, capability: str) -> bool:
    return capability in ROLE_CAPABILITIES[Role(role)]


def can_assign(actor: Role | str, requested: Role | str) -> bool:
    actor_role = Role(actor)
    requested_role = Role(requested)
    if requested_role is Role.OWNER:
        return actor_role is Role.OWNER
    return actor_role in {Role.OWNER, Role.ADMIN}
