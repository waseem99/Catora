from fastapi.testclient import TestClient

from catora_api.main import app


def test_liveness_contract() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "catora-api", "version": "0.1.0"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-request-id"]


def test_system_info() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/system/info")
    assert response.status_code == 200
    assert response.json()["name"] == "Catora"
