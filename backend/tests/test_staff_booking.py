"""Store appointment isolation, atomic decisions and actual customer-visible state."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import PostgresRepository, transaction
from app.domain import DomainError
from app.seed import OPERATOR, OTHER_STORE, STORE
from app.services import IdentityService
from app.staff_booking import DecisionInput, StaffBookingService
from tests.conftest import staff_headers
from tests.test_booking import confirmation, create_draft, ready, verify
from tests.test_customer_catalog import publish_catalog

BASE = f"/api/stores/{STORE}/appointments"


@pytest.fixture
def submitted(client: TestClient, settings: Settings) -> tuple[str, dict[str, str]]:
    publish_catalog(settings)
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    receipt = verify(client, thread, csrf, draft)
    result = client.post(
        f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm",
        headers=csrf,
        json=confirmation(draft, receipt),
    )
    assert result.status_code == 200, result.text
    return result.json()["id"], {"thread": thread}


def decision(**changes: Any) -> dict[str, Any]:
    return {
        "request_key": str(uuid4()),
        "expected_version": 1,
        "action": "confirm",
        "accepted": True,
        "availability_checked": True,
        **changes,
    }


def test_operator_confirmation_and_customer_state(
    client: TestClient, settings: Settings, submitted: tuple[str, dict[str, str]]
) -> None:
    appointment, data = submitted
    headers = staff_headers(client, "demo-operator")
    inbox = client.get(BASE, headers=headers).json()
    assert inbox["total"] == 1 and inbox["counts"] == {"pending_store_confirmation": 1}
    assert "19900000001" not in str(inbox)
    detail = client.get(f"{BASE}/{appointment}", headers=headers).json()
    assert detail["confirmation_method"] == "customer_button" and len(detail["events"]) == 1
    assert client.post(f"{BASE}/{appointment}/contact", headers=headers).json() == {
        "phone": "19900000001"
    }
    payload = decision()
    url = f"{BASE}/{appointment}/decision"
    response = client.post(url, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["version"] == 2 and result["state"] == "confirmed"
    assert datetime.fromisoformat(result["confirmed_at"]) == datetime.fromisoformat(
        result["desired_at"]
    )
    assert len(result["events"]) == 2
    assert client.post(url, headers=headers, json=payload).json() == result
    assert client.post(url, headers=headers, json={**payload, "accepted": False}).status_code == 409
    assert client.post(url, headers=headers, json=decision()).status_code == 409
    state = client.get(f"/api/threads/{data['thread']}/booking").json()["appointments"][0]
    assert state["state"] == "confirmed"
    assert datetime.fromisoformat(state["confirmed_at"]) == datetime.fromisoformat(
        result["confirmed_at"]
    )
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM staff_booking_idempotency") == {"n": 1}
        assert "19900000001" not in str(repo.all("SELECT * FROM audit"))
        assert repo.one("SELECT action FROM audit WHERE action='appointment.contact_read'")


@pytest.mark.parametrize("username", ["demo-author", "demo-reviewer", "demo-platform-admin"])
def test_no_implicit_customer_permissions(
    client: TestClient, submitted: tuple[str, dict[str, str]], username: str
) -> None:
    appointment, _ = submitted
    headers = staff_headers(client, username)
    for suffix in ("", f"/{appointment}"):
        assert client.get(BASE + suffix, headers=headers).status_code == 403
    assert client.post(f"{BASE}/{appointment}/contact", headers=headers).status_code == 403
    assert (
        client.post(f"{BASE}/{appointment}/decision", headers=headers, json=decision()).status_code
        == 403
    )


def test_operator_scope_and_split_grants(
    client: TestClient, settings: Settings, submitted: tuple[str, dict[str, str]]
) -> None:
    appointment, _ = submitted
    headers = staff_headers(client, "demo-operator")
    assert client.get(f"/api/stores/{OTHER_STORE}/appointments", headers=headers).status_code == 403
    assert client.get(f"/api/stores/{STORE}/knowledge", headers=headers).status_code == 403
    assert client.get(BASE).status_code == 401  # Visitor cookie cannot impersonate staff.
    assert client.get(f"{BASE}/{uuid4()}", headers=headers).status_code == 404
    with transaction(settings.database_url) as repo:
        repo.execute(
            "DELETE FROM store_grant WHERE staff_id=%s "
            "AND permission IN ('appointment_manage','appointment_contact')",
            (OPERATOR,),
        )
    assert client.get(BASE, headers=headers).status_code == 200
    assert client.post(f"{BASE}/{appointment}/contact", headers=headers).status_code == 403
    assert (
        client.post(f"{BASE}/{appointment}/decision", headers=headers, json=decision()).status_code
        == 403
    )
    client.post("/api/staff-sessions/logout", headers=headers)
    assert client.get(BASE, headers=headers).status_code == 401


@pytest.mark.parametrize(
    "changes",
    [
        {"accepted": False},
        {"availability_checked": False},
        {"expected_version": 2},
        {"action": "decline"},
    ],
)
def test_invalid_confirmation(
    client: TestClient, submitted: tuple[str, dict[str, str]], changes: dict[str, Any]
) -> None:
    appointment, _ = submitted
    headers = staff_headers(client, "demo-operator")
    assert client.post(
        f"{BASE}/{appointment}/decision", headers=headers, json=decision(**changes)
    ).status_code in (409, 422)
    assert client.get(f"{BASE}/{appointment}", headers=headers).json()["version"] == 1


def test_decline_and_withdrawn_policy(
    client: TestClient, settings: Settings, submitted: tuple[str, dict[str, str]]
) -> None:
    appointment, data = submitted
    headers = staff_headers(client, "demo-operator")
    with transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE knowledge_version SET status='withdrawn' "
            "WHERE knowledge_key='faq-online-application'"
        )
    assert (
        client.post(f"{BASE}/{appointment}/decision", headers=headers, json=decision()).status_code
        == 409
    )
    result = client.post(
        f"{BASE}/{appointment}/decision",
        headers=headers,
        json=decision(action="decline", reason="no_availability"),
    )
    assert result.status_code == 200 and result.json()["decision_reason"] == "no_availability"
    assert (
        client.get(f"/api/threads/{data['thread']}/booking").json()["appointments"][0]["state"]
        == "declined"
    )


def test_staff_decision_atomic_rollback_and_concurrency(
    client: TestClient,
    settings: Settings,
    submitted: tuple[str, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    appointment, _ = submitted
    headers = staff_headers(client, "demo-operator")
    with transaction(settings.database_url) as repo:
        actor = IdentityService(repo, settings).authenticate(headers["Authorization"][7:], "staff")
    payload = DecisionInput(**decision())
    audit = PostgresRepository.audit

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(PostgresRepository, "audit", fail)
    with pytest.raises(RuntimeError), transaction(settings.database_url) as repo:
        StaffBookingService(repo, settings, actor, STORE).decide(appointment, payload, str(uuid4()))
    monkeypatch.setattr(PostgresRepository, "audit", audit)
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT version FROM appointment WHERE id=%s", (appointment,)) == {
            "version": 1
        }
        assert repo.one("SELECT count(*) AS n FROM staff_booking_idempotency") == {"n": 0}

    def write() -> dict[str, Any]:
        with transaction(settings.database_url) as repo:
            return StaffBookingService(repo, settings, actor, STORE).decide(
                appointment, payload, str(uuid4())
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: write(), range(2)))
    assert results[0] == results[1] and results[0]["version"] == 2
    with transaction(settings.database_url) as repo:
        repo.execute(
            "DELETE FROM store_grant WHERE staff_id=%s AND permission='appointment_manage'",
            (OPERATOR,),
        )
    with pytest.raises(DomainError), transaction(settings.database_url) as repo:
        StaffBookingService(repo, settings, actor, STORE).decide(appointment, payload, str(uuid4()))
