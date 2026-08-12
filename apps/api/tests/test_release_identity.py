from __future__ import annotations

from catora_api.release_identity import runtime_release_identity


def _set_complete_identity(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CATORA_RELEASE_GIT_SHA", "a" * 40)
    monkeypatch.setenv("CATORA_RELEASE_CI_RUN_ID", "123456")
    monkeypatch.setenv("CATORA_RELEASE_IMAGE_TAG", "ghcr.io/waseem99/catora-api:sha-aaaa")
    monkeypatch.setenv("CATORA_RELEASE_IMAGE_DIGEST", "sha256:" + "b" * 64)
    monkeypatch.setenv("CATORA_RELEASE_PREVIOUS_IMAGE", "sha256:" + "c" * 64)


def test_runtime_release_identity_is_complete_only_with_provenance(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _set_complete_identity(monkeypatch)

    identity = runtime_release_identity("api")

    assert identity == {
        "component": "api",
        "git_sha": "a" * 40,
        "ci_run_id": "123456",
        "image_tag": "ghcr.io/waseem99/catora-api:sha-aaaa",
        "image_digest": "sha256:" + "b" * 64,
        "previous_image": "sha256:" + "c" * 64,
        "complete": True,
    }


def test_runtime_release_identity_fails_closed_on_invalid_digest(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _set_complete_identity(monkeypatch)
    monkeypatch.setenv("CATORA_RELEASE_IMAGE_DIGEST", "latest")

    identity = runtime_release_identity("worker")

    assert identity["complete"] is False
    assert identity["component"] == "worker"
