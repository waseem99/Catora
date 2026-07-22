from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from catora_api.taxonomy.schema import TaxonomyPackage

DEFAULT_TAXONOMY_RESOURCE = "furniture_home_v1.json"


class TaxonomyLoadError(ValueError):
    pass


def load_bundled_taxonomy(
    resource_name: str = DEFAULT_TAXONOMY_RESOURCE,
) -> TaxonomyPackage:
    resource = files("catora_api.taxonomy.data").joinpath(resource_name)
    try:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaxonomyLoadError(f"unable to load taxonomy resource {resource_name!r}") from exc
    return _validate_payload(payload, source=resource_name)


def load_taxonomy_path(path: Path) -> TaxonomyPackage:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaxonomyLoadError(f"unable to load taxonomy file {path}") from exc
    return _validate_payload(payload, source=str(path))


def _validate_payload(payload: object, *, source: str) -> TaxonomyPackage:
    if not isinstance(payload, dict):
        raise TaxonomyLoadError(f"taxonomy {source!r} must contain a JSON object")
    try:
        return TaxonomyPackage.model_validate(cast(dict[str, object], payload))
    except ValidationError as exc:
        raise TaxonomyLoadError(f"invalid taxonomy {source!r}: {exc}") from exc
