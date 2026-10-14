import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.schemas.health import HealthResponse


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_health_endpoint_root(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "nexora-backend"

    # Validate against Pydantic schema
    validated = HealthResponse(**data)
    assert validated.status == "healthy"
    assert validated.service == "nexora-backend"


def test_health_endpoint_v1(client: TestClient) -> None:
    settings = get_settings()
    response = client.get(f"{settings.API_V1_PREFIX}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "nexora-backend"


def test_cors_allowed_origin(client: TestClient) -> None:
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_disallowed_origin(client: TestClient) -> None:
    response = client.get(
        "/health",
        headers={"Origin": "http://malicious-site.example.com"},
    )
    assert response.status_code == 200
    # Disallowed origin should not have CORS header echoed back
    assert "access-control-allow-origin" not in response.headers
