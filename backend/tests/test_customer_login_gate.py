from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from tests.conftest import visitor_headers
from tests.test_customer_memory import PASSWORD


def test_default_requires_customer_login() -> None:
    assert Settings(_env_file=None, database_url="unused").customer_login_required is True


def test_guest_can_login_but_cannot_bypass_gate(settings: Settings) -> None:
    with TestClient(
        create_app(settings.model_copy(update={"customer_login_required": True}))
    ) as app:
        csrf = visitor_headers(app)
        assert app.get("/api/visitor-sessions/current").status_code == 200
        assert app.get("/api/customer/session").json() == {"customer": None}
        assert app.get("/api/public/stores").status_code == 200
        for path in ("/api/catalog/projects", "/api/threads", f"/api/threads/{uuid4()}/messages"):
            denied = app.get(path)
            assert denied.status_code == 401, denied.text
            assert denied.json()["code"] == "customer_login_required"
        assert app.post("/api/threads", headers=csrf).status_code == 401
        assert (
            app.post(
                f"/api/threads/{uuid4()}/messages",
                headers=csrf,
                json={"message_id": str(uuid4()), "question": "你好"},
            ).status_code
            == 401
        )
        assert app.post("/api/visitor-sessions/logout", headers=csrf).status_code == 200


def test_register_with_explicit_consent_enters_platform_and_restores_on_login(
    settings: Settings,
) -> None:
    with TestClient(
        create_app(settings.model_copy(update={"customer_login_required": True}))
    ) as app:
        guest = visitor_headers(app)
        response = app.post(
            "/api/customer-accounts",
            headers=guest,
            json={
                "username": "gate-user",
                "password": PASSWORD,
                "bind_current": True,
                "enable_memory": True,
            },
        )
        assert response.status_code == 201, response.text
        csrf = {"X-CSRF-Token": response.json()["csrf_token"]}
        # The normal page only fetches this minimal identity endpoint.
        assert app.get("/api/customer/session").json() == {"customer": {"username": "gate-user"}}
        assert app.get("/api/customer/me").json()["customer"]["memory_enabled"] is True
        created = app.post("/api/threads", headers=csrf)
        assert created.status_code == 201, created.text
        thread = created.json()["thread_id"]
        assert app.post("/api/visitor-sessions/logout", headers=csrf).status_code == 200
        guest = visitor_headers(app)
        assert app.get(f"/api/threads/{thread}/messages").status_code == 401
        login = app.post(
            "/api/customer-sessions",
            headers=guest,
            json={
                "username": "gate-user",
                "password": PASSWORD,
            },
        )
        assert login.status_code == 200, login.text
        assert app.get(f"/api/threads/{thread}/messages").status_code == 200
        # Not re-checking the optional box never silently clears an earlier consent.
        assert app.get("/api/customer/me").json()["customer"]["memory_enabled"] is True


@pytest.mark.parametrize("consent", [None, False])
def test_registration_requires_preference_consent(settings: Settings, consent: bool | None) -> None:
    with TestClient(
        create_app(settings.model_copy(update={"customer_login_required": True}))
    ) as app:
        guest = visitor_headers(app)
        payload = {
            "username": "no-memory",
            "password": PASSWORD,
            "bind_current": True,
        }
        if consent is not None:
            payload["enable_memory"] = consent
        result = app.post(
            "/api/customer-accounts",
            headers=guest,
            json=payload,
        )
        assert result.status_code == 409, result.text
        assert result.json()["code"] == "memory_consent_required"
        assert "set-cookie" not in result.headers
        assert app.get("/api/customer/session").json() == {"customer": None}
