from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

CURRENT_SCHEMA_REVISION = "0024"
_REQUIRED_SCHEMA_CHAIN = {
    "0022": "0021",
    "0023": "0022",
    "0024": "0023",
}
_REQUIRED_TABLES = {
    "local_profile_provider_accounts",
    "local_profile_observations",
    "branch_local_profile_links",
    "local_profile_conflicts",
    "review_provider_accounts",
    "review_observations",
    "review_analyses",
    "review_response_drafts",
}
_REQUIRED_ROUTES = {
    "/api/v1/workspaces/{workspace_id}/local-profile-accounts",
    "/api/v1/workspaces/{workspace_id}/local-profile-accounts/{account_id}/sync-synthetic",
    "/api/v1/workspaces/{workspace_id}/local-profile-observations",
    "/api/v1/workspaces/{workspace_id}/local-profile-links",
    "/api/v1/workspaces/{workspace_id}/local-profile-links/{link_id}",
    "/api/v1/workspaces/{workspace_id}/local-profile-conflicts",
    "/api/v1/workspaces/{workspace_id}/review-observations/import-synthetic",
    "/api/v1/workspaces/{workspace_id}/review-observations/{review_id}/response-drafts",
    "/api/v1/workspaces/{workspace_id}/review-analyses",
}
_REQUIRED_SETTINGS = {
    "local_profile_intelligence_enabled",
    "reputation_intelligence_enabled",
}


class ReleaseIntegrityError(RuntimeError):
    pass


def validate_release_integrity(api_root: Path | None = None) -> dict[str, Any]:
    root = api_root or Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    script = ScriptDirectory.from_config(config)

    heads = tuple(script.get_heads())
    if heads != (CURRENT_SCHEMA_REVISION,):
        raise ReleaseIntegrityError(
            f"Expected exactly one Alembic head {CURRENT_SCHEMA_REVISION}; found {heads}"
        )

    revisions = {revision.revision: revision for revision in script.walk_revisions()}
    for revision_id, expected_parent in _REQUIRED_SCHEMA_CHAIN.items():
        revision = revisions.get(revision_id)
        if revision is None:
            raise ReleaseIntegrityError(f"Missing required Alembic revision {revision_id}")
        if revision.down_revision != expected_parent:
            raise ReleaseIntegrityError(
                f"Revision {revision_id} must revise {expected_parent}; "
                f"found {revision.down_revision}"
            )

    from catora_api.config import Settings
    from catora_api.db import Base
    from catora_api.main import app

    missing_tables = sorted(_REQUIRED_TABLES.difference(Base.metadata.tables))
    if missing_tables:
        raise ReleaseIntegrityError(
            f"Persistence models are not registered for tables: {missing_tables}"
        )

    openapi_paths = app.openapi().get("paths")
    if not isinstance(openapi_paths, dict):
        raise ReleaseIntegrityError("FastAPI did not produce an OpenAPI paths object")
    paths = {path for path in openapi_paths if isinstance(path, str)}
    missing_routes = sorted(_REQUIRED_ROUTES.difference(paths))
    if missing_routes:
        raise ReleaseIntegrityError(
            f"Application routers are not registered for paths: {missing_routes}"
        )

    missing_settings = sorted(_REQUIRED_SETTINGS.difference(Settings.model_fields))
    if missing_settings:
        raise ReleaseIntegrityError(
            f"Feature flags are not defined in typed Settings: {missing_settings}"
        )

    return {
        "schema_head": heads[0],
        "registered_tables": len(Base.metadata.tables),
        "registered_routes": len(paths),
        "checked_tables": len(_REQUIRED_TABLES),
        "checked_routes": len(_REQUIRED_ROUTES),
        "checked_settings": len(_REQUIRED_SETTINGS),
    }


def main() -> None:
    result = validate_release_integrity()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
