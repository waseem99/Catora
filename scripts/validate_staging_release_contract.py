from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str


def _check(name: str, condition: bool, success: str, failure: str) -> Check:
    return Check(name=name, ok=condition, detail=success if condition else failure)


def _text(root: Path, path: str) -> str:
    return (root / path).read_text(encoding="utf-8")


def validate(root: Path) -> list[Check]:
    env = _text(root, ".env.example")
    release_identity = _text(root, "apps/api/catora_api/release_identity.py")
    api_main = _text(root, "apps/api/catora_api/main.py")
    worker = _text(root, "apps/api/catora_api/worker.py")
    web_release = _text(root, "apps/web/app/api/release/route.ts")
    backend_proxy = _text(root, "apps/web/app/api/backend/[...path]/route.ts")
    browser = _text(root, "scripts/staging_browser_certification.py")
    visual = _text(root, "scripts/staging_visual_certification.py")
    certify = _text(root, "scripts/staging_certify.py")
    seed = _text(root, "apps/api/scripts/seed_staging_certification.py")
    images = _text(root, ".github/workflows/release-images.yml")
    deploy = _text(root, ".github/workflows/staging-deploy-compose.yml")
    workflow = _text(root, ".github/workflows/staging-certification.yml")
    uat = _text(root, ".github/workflows/uat-record.yml")
    compose = _text(root, "deploy/portable/docker-compose.staging.yml")

    release_env = {
        "CATORA_RELEASE_GIT_SHA=",
        "CATORA_RELEASE_CI_RUN_ID=",
        "CATORA_RELEASE_IMAGE_TAG=",
        "CATORA_RELEASE_IMAGE_DIGEST=",
        "CATORA_RELEASE_PREVIOUS_IMAGE=",
    }
    checks = [
        _check(
            "release.env_contract",
            release_env.issubset(set(env.splitlines())),
            "runtime release provenance names are documented with blank defaults",
            "all non-secret CATORA_RELEASE_* provenance variables must be documented blank",
        ),
        _check(
            "release.identity_validation",
            "_GIT_SHA_RE" in release_identity
            and "_IMAGE_DIGEST_RE" in release_identity
            and 'and bool(previous_image)' in release_identity,
            "runtime release identity fails closed on malformed/incomplete evidence",
            "release identity must validate SHA, digest and rollback reference",
        ),
        _check(
            "release.api_endpoints",
            '@app.get("/health/release"' in api_main
            and '@app.get("/health/worker"' in api_main
            and 'send_task("catora.system.ping")' in api_main,
            "API exposes API identity and proves worker identity with a real Celery ping",
            "API must expose /health/release and /health/worker using a real worker task",
        ),
        _check(
            "release.worker_identity",
            '"release": runtime_release_identity("worker")' in worker,
            "worker ping reports the running worker release",
            "worker ping must report runtime release identity",
        ),
        _check(
            "release.web_identity",
            'component: "web"' in web_release
            and "CATORA_RELEASE_IMAGE_DIGEST" in web_release
            and "previousImage.length > 0" in web_release,
            "web exposes fail-closed runtime release identity",
            "web /api/release must report complete running provenance",
        ),
        _check(
            "release.web_runtime_api",
            "process.env.CATORA_API_URL" in backend_proxy
            and 'export const POST = proxy' in backend_proxy
            and 'export const DELETE = proxy' in backend_proxy,
            "browser API origin is runtime-configurable through same-origin proxy",
            "web must not require a rebuild just to change API origin",
        ),
        _check(
            "release.immutable_images",
            "docker/build-push-action@v7" in images
            and "org.opencontainers.image.revision" in images
            and "steps.build.outputs.digest" in images
            and "catora-release-manifest.json" in images
            and "packages: write" in images,
            "GHCR workflow publishes immutable digest evidence from one Git SHA",
            "release workflow must publish and record immutable web/API/worker digests",
        ),
        _check(
            "staging.digest_deployment",
            "catora-api@${CATORA_STAGING_API_IMAGE_DIGEST" in compose
            and "catora-worker@${CATORA_STAGING_WORKER_IMAGE_DIGEST" in compose
            and "catora-web@${CATORA_STAGING_WEB_IMAGE_DIGEST" in compose
            and '["alembic", "upgrade", "head"]' in compose,
            "portable staging deploys digest-addressed images and a single migration step",
            "staging compose must deploy exact digests and preserve migration ownership",
        ),
        _check(
            "staging.private_default",
            "${CATORA_STAGING_WEB_BIND:-127.0.0.1}:3000:3000" in compose
            and "${CATORA_STAGING_API_BIND:-127.0.0.1}:8000:8000" in compose,
            "portable staging binds web/API to loopback by default",
            "staging must not be publicly exposed by default",
        ),
        _check(
            "staging.qa_seed_guard",
            "I_UNDERSTAND_THIS_IS_STAGING_ONLY" in seed
            and "@staging.catora.local" in seed
            and "delete(Membership).where(Membership.user_id == no_membership_user.id)" in seed,
            "staging fixture seed is explicitly guarded and creates no-membership isolation fixture",
            "staging identities must be protected from accidental production use",
        ),
        _check(
            "staging.playwright_real_code",
            "sync_playwright()" in browser
            and '"desktop-chromium"' in browser
            and '"mobile-chromium"' in browser
            and "_direct_api_headers" in browser
            and "expected 403" in browser,
            "real desktop/mobile Playwright and direct-API RBAC assertions exist",
            "browser certification must contain executable Playwright/RBAC tests",
        ),
        _check(
            "staging.visual_gate",
            "sync_playwright()" in visual
            and "VISUAL REVIEW REQUIRED" in visual
            and "qa/visual-baselines" in visual,
            "visual regression requires approved baselines and explicit review",
            "visual baselines must not be silently auto-updated",
        ),
        _check(
            "staging.three_state_gate",
            all(value in certify for value in ("READY FOR UAT", "FAILED", "BLOCKED"))
            and "_prove_identities" in certify
            and "_run_browser" in certify
            and "_run_visual" in certify,
            "certification has identity/runtime/browser/visual gates and three-state decision",
            "certification may emit only READY FOR UAT, FAILED or BLOCKED",
        ),
        _check(
            "staging.manual_recovery",
            "workflow_dispatch:" in workflow
            and "repository_dispatch:" in workflow
            and "catora-staging-deployed" in workflow
            and "environment: staging" in workflow,
            "standalone staging certification supports controlled manual/external triggers",
            "staging certification workflow must remain provider-neutral and recoverable",
        ),
        _check(
            "staging.automatic_deploy_certify",
            "workflow_run:" in deploy
            and 'workflows: ["Immutable release images"]' in deploy
            and "catora-release-manifest-" in deploy
            and "python scripts/staging_certify.py" in deploy
            and "environment: staging" in deploy,
            "successful main release images automatically feed private staging certification",
            "private staging deploy must consume release manifest and invoke certification",
        ),
        _check(
            "uat.explicit_human_boundary",
            "workflow_dispatch:" in uat
            and "environment: uat" in uat
            and 'report.get("decision") != "READY FOR UAT"' in uat
            and "This workflow does not deploy production" in uat,
            "human UAT is explicit, evidence-bound and cannot deploy production",
            "UAT workflow must verify READY FOR UAT and remain non-deploying",
        ),
    ]
    return checks


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    checks = validate(root)
    for check in checks:
        print(f"[{'ok' if check.ok else 'error'}] {check.name}: {check.detail}")
    ok = all(check.ok for check in checks)
    print(f"Staging release contract: {'valid' if ok else 'invalid'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
