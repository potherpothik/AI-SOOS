from app.config import Settings
from app.main import app
from fastapi.testclient import TestClient


def test_health_reports_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "0.1.0"


def test_budget_defaults_are_bounded() -> None:
    settings = Settings()
    assert settings.max_task_retries <= 5
    assert settings.monthly_budget_usd >= 0
