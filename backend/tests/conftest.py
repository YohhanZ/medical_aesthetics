import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

from app.api import create_app
from app.config import Settings
from app.db import transaction
from app.migrate import migrate
from app.seed import seed

PASSWORD = "Synthetic-test-password-2026!"


@pytest.fixture
def settings() -> Settings:
    dsn = os.environ.get("MA_TEST_DATABASE_URL", "")
    config = conninfo_to_dict(dsn)
    if config.get("dbname") != "ma_m1_test" or config.get("port") != "55434":
        raise RuntimeError("Tests require isolated ma_m1_test database on port 55434")
    migrate(dsn)
    with transaction(dsn) as repo:
        # Only this named, isolated test DB is reset. Never reset a configured business DB.
        repo.execute("TRUNCATE tenant,login_bucket RESTART IDENTITY CASCADE")
    settings = Settings(
        database_url=dsn,
        environment="test",
        agent_runtime="inprocess",
        allow_simulated_data=True,
        demo_medical_education=False,
        cookie_secure=False,
        allowed_origins=["http://localhost"],
        milvus_collection="ma_mock_test_256",
        model_api_key="test-only-not-a-real-key",
        model_export_hashes=[],
        booking_sms_provider="simulated",
        booking_encryption_key="ZGV2LXRlc3QtZW5jcnlwdGlvbi1rZXktMzJieXRlcyE=",
        booking_hmac_key="synthetic-test-only-hmac-secret-32chars",
    )
    seed(settings, PASSWORD)
    return settings


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client


def staff_headers(client: TestClient, username: str = "demo-author") -> dict[str, str]:
    result = client.post("/api/staff-sessions", json={"username": username, "password": PASSWORD})
    assert result.status_code == 200, result.text
    return {"Authorization": f"Bearer {result.json()['access_token']}"}


def visitor_headers(client: TestClient, store: str = "demo-shanghai") -> dict[str, str]:
    result = client.post("/api/visitor-sessions", json={"store_code": store})
    assert result.status_code == 201, result.text
    return {"X-CSRF-Token": result.json()["csrf_token"]}
