from __future__ import annotations

import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CERTIFICATION = runpy.run_path(str(ROOT / "scripts" / "staging_certify.py"))
BlockedError = CERTIFICATION["BlockedError"]
identity = CERTIFICATION["_identity"]


def _payload() -> dict[str, object]:
    return {
        "component": "api",
        "git_sha": "a" * 40,
        "ci_run_id": "42",
        "image_tag": "ghcr.io/waseem99/catora-api:sha-aaaa",
        "image_digest": "sha256:" + "b" * 64,
        "previous_image": "sha256:" + "c" * 64,
        "complete": True,
    }


def test_identity_gate_accepts_exact_running_artifact() -> None:
    result = identity(
        component="api",
        payload=_payload(),
        expected_sha="a" * 40,
        expected_ci_run_id="42",
        expected_digest="sha256:" + "b" * 64,
    )

    assert result["git_sha"] == "a" * 40
    assert result["image_digest"] == "sha256:" + "b" * 64


def test_identity_gate_blocks_wrong_running_digest() -> None:
    with pytest.raises(BlockedError, match="image digest mismatch"):
        identity(
            component="api",
            payload=_payload(),
            expected_sha="a" * 40,
            expected_ci_run_id="42",
            expected_digest="sha256:" + "d" * 64,
        )


def test_identity_gate_blocks_incomplete_runtime_evidence() -> None:
    payload = _payload()
    payload["complete"] = False

    with pytest.raises(BlockedError, match="identity is incomplete"):
        identity(
            component="api",
            payload=payload,
            expected_sha="a" * 40,
            expected_ci_run_id="42",
            expected_digest="sha256:" + "b" * 64,
        )
