import asyncio

from fastapi.testclient import TestClient

from catora_api.config import Settings
from catora_api.main import _check_storage, app


def test_liveness_contract() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "catora-api", "version": "0.1.0"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]


def test_storage_readiness_uses_bucket_scoped_operation(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeS3Client:
        def list_objects_v2(self, **kwargs: object) -> None:
            calls.append(kwargs)

    def fake_client(*args: object, **kwargs: object) -> FakeS3Client:
        assert args == ("s3",)
        assert kwargs["endpoint_url"] == "https://storage.railway.app"
        return FakeS3Client()

    monkeypatch.setattr("catora_api.main.boto3.client", fake_client)
    settings = Settings(
        s3_endpoint_url="https://storage.railway.app",
        s3_access_key="access",
        s3_secret_key="secret",
        s3_bucket="catora-storage-example",
    )

    asyncio.run(_check_storage(settings))

    assert calls == [{"Bucket": "catora-storage-example", "MaxKeys": 1}]


def test_system_info() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/system/info")
    assert response.status_code == 200
    assert response.json()["name"] == "Catora"
