from pathlib import Path


def test_api_dockerfile_uses_installed_asgi_server() -> None:
    root = Path(__file__).resolve().parents[3]
    dockerfile = (root / "apps/api/Dockerfile").read_text(encoding="utf-8")

    assert 'CMD ["uvicorn", "catora_api.main:app"' in dockerfile
    assert 'CMD ["fastapi", "run"' not in dockerfile
