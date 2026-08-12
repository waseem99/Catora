from __future__ import annotations

import os
import re
from typing import TypedDict

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ReleaseIdentity(TypedDict):
    component: str
    git_sha: str
    ci_run_id: str
    image_tag: str
    image_digest: str
    previous_image: str
    complete: bool


def _value(name: str) -> str:
    return os.getenv(name, "").strip()


def runtime_release_identity(component: str) -> ReleaseIdentity:
    git_sha = _value("CATORA_RELEASE_GIT_SHA").lower()
    ci_run_id = _value("CATORA_RELEASE_CI_RUN_ID")
    image_tag = _value("CATORA_RELEASE_IMAGE_TAG")
    image_digest = _value("CATORA_RELEASE_IMAGE_DIGEST").lower()
    previous_image = _value("CATORA_RELEASE_PREVIOUS_IMAGE")
    complete = (
        bool(_GIT_SHA_RE.fullmatch(git_sha))
        and bool(ci_run_id)
        and bool(image_tag)
        and bool(_IMAGE_DIGEST_RE.fullmatch(image_digest))
        and bool(previous_image)
    )
    return {
        "component": component,
        "git_sha": git_sha,
        "ci_run_id": ci_run_id,
        "image_tag": image_tag,
        "image_digest": image_digest,
        "previous_image": previous_image,
        "complete": complete,
    }
