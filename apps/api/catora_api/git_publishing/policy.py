from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath

from catora_api.git_publishing.models import (
    GIT_PUBLISHING_CONTRACT_VERSION,
    GitPatchItem,
    GitPatchManifest,
    GitRepositoryConfiguration,
)

_FORBIDDEN_EXACT = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "vercel.json",
        "railway.toml",
        "Dockerfile",
    }
)
_FORBIDDEN_PREFIXES = (
    ".git/",
    ".github/workflows/",
    "infra/",
    "terraform/",
    "deploy/",
    "secrets/",
)
_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)"
    r"\s*[:=]\s*['\"]?[A-Za-z0-9_./+=:-]{12,}"
)
_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")


class GitPublishingPolicyError(ValueError):
    pass


def canonical_json(value: object) -> str:
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json", exclude_none=True)  # type: ignore[attr-defined]
    else:
        payload = value
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_repository_path(path: str) -> str:
    candidate = path.replace("\\", "/").strip()
    parsed = PurePosixPath(candidate)
    if not candidate or candidate.startswith("/") or ".." in parsed.parts:
        raise GitPublishingPolicyError("Repository path must be relative and cannot traverse")
    normalized = str(parsed)
    if normalized == "." or normalized.startswith("./"):
        raise GitPublishingPolicyError("Repository path is invalid")
    if normalized in _FORBIDDEN_EXACT or normalized.startswith(_FORBIDDEN_PREFIXES):
        raise GitPublishingPolicyError("Repository path is outside the publishing boundary")
    return normalized


def validate_proposal_branch(
    branch: str,
    *,
    protected_branches: tuple[str, ...],
) -> str:
    value = branch.strip()
    if not _BRANCH_PATTERN.fullmatch(value):
        raise GitPublishingPolicyError("Proposal branch name is invalid")
    if value in protected_branches:
        raise GitPublishingPolicyError("Proposal branch cannot be a protected branch")
    if value.startswith("refs/") or "//" in value or value.endswith(("/", ".")):
        raise GitPublishingPolicyError("Proposal branch name is invalid")
    return value


def validate_patch_item(
    item: GitPatchItem,
    *,
    configuration: GitRepositoryConfiguration,
) -> GitPatchItem:
    path = normalize_repository_path(item.path)
    allowed = any(
        path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
        for prefix in configuration.allowed_paths
    )
    if not allowed:
        raise GitPublishingPolicyError(f"Path '{path}' is not allowlisted")
    if _SECRET_PATTERN.search(item.content):
        raise GitPublishingPolicyError(f"Path '{path}' contains secret-like content")
    if sha256_text(item.content) != item.content_sha256:
        raise GitPublishingPolicyError(f"Path '{path}' content hash does not match")
    if not item.evidence:
        raise GitPublishingPolicyError(f"Path '{path}' requires source evidence")
    return item.model_copy(update={"path": path})


def build_patch_manifest(
    *,
    configuration: GitRepositoryConfiguration,
    base_revision: str,
    proposal_branch: str,
    title: str,
    body: str,
    items: tuple[GitPatchItem, ...],
    rollback_plan: str,
    idempotency_key: str,
) -> GitPatchManifest:
    branch = validate_proposal_branch(
        proposal_branch,
        protected_branches=configuration.protected_branches,
    )
    validated = tuple(
        validate_patch_item(item, configuration=configuration) for item in items
    )
    core = {
        "contract_version": GIT_PUBLISHING_CONTRACT_VERSION,
        "repository_full_name": configuration.repository_full_name,
        "base_revision": base_revision,
        "proposal_branch": branch,
        "title": title,
        "body": body,
        "items": [item.model_dump(mode="json", exclude_none=True) for item in validated],
        "rollback_plan": rollback_plan,
        "idempotency_key": idempotency_key,
    }
    return GitPatchManifest(
        **core,
        manifest_sha256=sha256_text(canonical_json(core)),
    )


def verify_manifest(manifest: GitPatchManifest) -> None:
    core = manifest.model_dump(mode="json", exclude={"manifest_sha256"}, exclude_none=True)
    if sha256_text(canonical_json(core)) != manifest.manifest_sha256:
        raise GitPublishingPolicyError("Git proposal manifest hash does not match")
