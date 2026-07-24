from pathlib import Path


def test_worker_dockerfile_uses_bounded_non_root_runtime() -> None:
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "apps/worker/Dockerfile").read_text(encoding="utf-8")

    assert "USER catora" in dockerfile
    assert '"--concurrency=2"' in dockerfile
    assert '"--prefetch-multiplier=1"' in dockerfile
    assert '"--max-tasks-per-child=100"' in dockerfile
