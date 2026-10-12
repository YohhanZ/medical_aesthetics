"""Scoped visit records, append-only history and personal confirmation on isolated PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.consultation_cases import (
    ACCEPT_TEXT,
    REJECT_TEXT,
    CaseDecision,
    CaseRevision,
    ConsultationCases,
)
from app.db import PostgresRepository, transaction
from app.domain import DomainError
from app.seed import CONSULTANT, OTHER_STORE, STORE
from app.services import IdentityService
from tests.conftest import staff_headers, visitor_headers
from tests.test_booking import confirmation, create_draft, ready, verify
from tests.test_booking_lifecycle import booking as booking
from tests.test_staff_booking import decision

BASE = f"/api/stores/{STORE}/consultations"


def revision(version: int = 1, **changes: Any) -> dict[str, Any]:
    return {
        "request_key": str(uuid4()),
        "expected_version": version,
        "accepted": True,
        "name": "合成到店访客",
        "intention": "基础补水护理方向沟通",
        "reason": "到店后继续了解",
        "project_version_id": None,
        **changes,
    }


@pytest.fixture
def arrived(client: TestClient, booking: dict[str, Any]) -> dict[str, Any]:
    assert (
        client.post(
            f"/api/stores/{STORE}/appointments/{booking['id']}/decision",
            headers=booking["staff"],
            json=decision(),
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/stores/{STORE}/appointments/{booking['id']}/arrive",
            headers=booking["staff"],
            json={
                "request_key": str(uuid4()),
                "expected_version": 2,
                "accepted": True,
                "identity_checked": True,
            },
        ).status_code
        == 200
    )
    booking["consultant"] = staff_headers(client, "demo-consultant")
    return booking


def create(client: TestClient, arrived: dict[str, Any]) -> dict[str, Any]:
    body = {
        "request_key": str(uuid4()),
        "appointment_id": arrived["id"],
        "expected_appointment_version": 3,
        "accepted": True,
    }
    response = client.post(BASE, headers=arrived["consultant"], json=body)
    assert response.status_code == 200, response.text
    assert client.post(BASE, headers=arrived["consultant"], json=body).json() == response.json()
    return dict(response.json())


def customer_url(booking: dict[str, Any]) -> str:
    return f"/api/threads/{booking['thread']}/appointments/{booking['id']}/consultation"


def confirm_body(row: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "request_key": str(uuid4()),
        "expected_version": row["version"],
        "accepted": True,
        "decision": "accept",
        "snapshot_hash": row["current"]["snapshot_hash"],
        "confirmation_text": ACCEPT_TEXT,
        **changes,
    }


def test_original_revisions_customer_confirmation_and_reopen(
    client: TestClient,
    settings: Settings,
    arrived: dict[str, Any],
) -> None:
    row = create(client, arrived)
    assert row["initial"]["intention"] == "不确定项目，先咨询"
    assert row["current"]["source"] == "original_application"
    assert client.get(customer_url(arrived)).json() == row
    updated = client.post(
        f"{BASE}/{row['id']}/revisions", headers=arrived["consultant"], json=revision()
    )
    assert updated.status_code == 200, updated.text
    row = updated.json()
    assert row["version"] == 2 and row["initial"]["intention"] == "不确定项目，先咨询"
    body = confirm_body(row)
    url = customer_url(arrived) + "/decision"
    accepted = client.post(url, headers=arrived["csrf"], json=body)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["current"]["decision"] == "accept"
    assert client.post(url, headers=arrived["csrf"], json=body).json() == accepted.json()
    assert (
        client.post(url, headers=arrived["csrf"], json={**body, "accepted": False}).status_code
        == 409
    )
    reopened = client.post(
        f"{BASE}/{row['id']}/revisions",
        headers=arrived["consultant"],
        json=revision(2, intention="清洁护理方向沟通"),
    ).json()
    assert reopened["version"] == 3 and reopened["current"]["decision"] is None
    assert reopened["history"][1]["decision"] == "accept"
    assert client.post(url, headers=arrived["csrf"], json=body).json()["version"] == 3
    assert client.get(BASE, headers=arrived["consultant"]).json()["total"] == 1
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM consultation_revision") == {"n": 3}
        assert repo.one("SELECT count(*) AS n FROM consultation_decision") == {"n": 1}
        assert "19900000001" not in str(repo.all("SELECT * FROM consultation_revision"))
        assert "19900000001" not in str(repo.all("SELECT * FROM audit"))


def test_customer_rejects_then_consultant_revises(
    client: TestClient, arrived: dict[str, Any]
) -> None:
    row = create(client, arrived)
    url = customer_url(arrived) + "/decision"
    rejected = client.post(
        url,
        headers=arrived["csrf"],
        json=confirm_body(row, decision="reject", confirmation_text=REJECT_TEXT),
    )
    assert rejected.status_code == 200 and rejected.json()["current"]["decision"] == "reject"
    assert client.post(url, headers=arrived["csrf"], json=confirm_body(row)).status_code == 409
    row = client.post(
        f"{BASE}/{row['id']}/revisions", headers=arrived["consultant"], json=revision()
    ).json()
    assert client.post(url, headers=arrived["csrf"], json=confirm_body(row)).status_code == 200
    assert row["history"][0]["decision"] == "reject"


@pytest.mark.parametrize("mutation", ["version", "hash", "accepted", "text", "grant", "project"])
def test_invalid_confirmation_has_no_decision(
    client: TestClient,
    settings: Settings,
    arrived: dict[str, Any],
    mutation: str,
) -> None:
    row = create(client, arrived)
    if mutation == "project":
        options = client.get(
            f"/api/stores/{STORE}/consultation-options", headers=arrived["consultant"]
        ).json()["items"]
        row = client.post(
            f"{BASE}/{row['id']}/revisions",
            headers=arrived["consultant"],
            json=revision(project_version_id=options[0]["id"]),
        ).json()
        with transaction(settings.database_url) as repo:
            repo.execute(
                "UPDATE knowledge_version SET status='withdrawn' WHERE id=%s", (options[0]["id"],)
            )
    body = confirm_body(row)
    if mutation == "version":
        body["expected_version"] += 1
    elif mutation == "hash":
        body["snapshot_hash"] = "0" * 64
    elif mutation == "accepted":
        body["accepted"] = False
    elif mutation == "text":
        body["confirmation_text"] = "I agree"
    elif mutation == "grant":
        with transaction(settings.database_url) as repo:
            repo.execute(
                "DELETE FROM store_grant WHERE staff_id=%s AND permission='customer_manage'",
                (CONSULTANT,),
            )
    result = client.post(customer_url(arrived) + "/decision", headers=arrived["csrf"], json=body)
    assert result.status_code in (409, 422, 404), result.text
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM consultation_decision") == {"n": 0}


def test_scopes_csrf_roles_and_read_only(
    client: TestClient, settings: Settings, arrived: dict[str, Any]
) -> None:
    row = create(client, arrived)
    for username in ("demo-operator", "demo-author", "demo-platform-admin"):
        headers = staff_headers(client, username)
        assert client.get(BASE, headers=headers).status_code == 403
        assert (
            client.post(
                f"{BASE}/{row['id']}/revisions", headers=headers, json=revision()
            ).status_code
            == 403
        )
    assert (
        client.get(
            f"/api/stores/{OTHER_STORE}/consultations", headers=arrived["consultant"]
        ).status_code
        == 403
    )
    assert client.get(BASE).status_code == 401
    url = customer_url(arrived)
    assert client.post(url + "/decision", json=confirm_body(row)).status_code == 403
    client.cookies.clear()
    csrf = visitor_headers(client)
    thread = client.post("/api/threads", headers=csrf).json()["thread_id"]
    assert client.get(url).status_code == 404
    other = f"/api/threads/{thread}/appointments/{arrived['id']}/consultation"
    assert client.get(other).status_code == 404
    assert client.post(other + "/decision", headers=csrf, json=confirm_body(row)).status_code == 404
    with transaction(settings.database_url) as repo:
        repo.execute(
            "DELETE FROM store_grant WHERE staff_id=%s AND permission='customer_manage'",
            (CONSULTANT,),
        )
    assert client.get(BASE, headers=arrived["consultant"]).status_code == 200
    assert (
        client.post(
            f"{BASE}/{row['id']}/revisions", headers=arrived["consultant"], json=revision()
        ).status_code
        == 403
    )


def test_only_arrived_and_no_merge_by_phone(client: TestClient, booking: dict[str, Any]) -> None:
    headers = staff_headers(client, "demo-consultant")
    assert client.get(customer_url(booking)).json() is None
    response = client.post(
        BASE,
        headers=headers,
        json={
            "request_key": str(uuid4()),
            "appointment_id": booking["id"],
            "expected_appointment_version": 1,
            "accepted": True,
        },
    )
    assert response.status_code == 409
    assert client.get(BASE, headers=headers).json()["total"] == 0


def test_revision_atomic_and_concurrent_replay(
    client: TestClient,
    settings: Settings,
    arrived: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = create(client, arrived)
    with transaction(settings.database_url) as repo:
        actor = IdentityService(repo, settings).authenticate(
            arrived["consultant"]["Authorization"][7:], "staff"
        )
    data = CaseRevision(**revision())
    audit = PostgresRepository.audit

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(PostgresRepository, "audit", fail)
    with pytest.raises(RuntimeError), transaction(settings.database_url) as repo:
        ConsultationCases(repo, settings, actor, STORE).update(row["id"], data, str(uuid4()))
    monkeypatch.setattr(PostgresRepository, "audit", audit)

    def write() -> dict[str, Any]:
        with transaction(settings.database_url) as repo:
            return ConsultationCases(repo, settings, actor, STORE).update(
                row["id"], data, str(uuid4())
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: write(), range(2)))
    assert results[0] == results[1] and results[0]["version"] == 2
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM consultation_revision") == {"n": 2}
        assert repo.one("SELECT count(*) AS n FROM consultation_decision") == {"n": 0}
    with pytest.raises(DomainError), transaction(settings.database_url) as repo:
        ConsultationCases(repo, settings, actor, STORE).update(
            row["id"], CaseRevision(**revision()), str(uuid4())
        )


def test_customer_confirmation_races_new_revision(
    client: TestClient,
    settings: Settings,
    arrived: dict[str, Any],
) -> None:
    row = create(client, arrived)
    with transaction(settings.database_url) as repo:
        staff = IdentityService(repo, settings).authenticate(
            arrived["consultant"]["Authorization"][7:], "staff"
        )
        visitor = IdentityService(repo, settings).authenticate(
            client.cookies["ma_visitor"], "visitor", arrived["csrf"]["X-CSRF-Token"]
        )

    def write(operation: str) -> str:
        try:
            with transaction(settings.database_url) as repo:
                if operation == "revise":
                    ConsultationCases(repo, settings, staff, STORE).update(
                        row["id"], CaseRevision(**revision()), str(uuid4())
                    )
                else:
                    ConsultationCases(repo, settings, visitor, STORE, arrived["thread"]).decide(
                        arrived["id"], CaseDecision(**confirm_body(row)), str(uuid4())
                    )
            return "success"
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, ["revise", "confirm"]))
    assert results[0] == "success" and results[1] in ("success", "consultation_state_conflict")
    latest = client.get(f"{BASE}/{row['id']}", headers=arrived["consultant"]).json()
    assert latest["version"] == 2 and latest["current"]["decision"] is None
    assert latest["history"][0]["decision"] in ("accept", None)


def test_same_phone_does_not_merge_visitors_or_records(
    client: TestClient,
    settings: Settings,
    arrived: dict[str, Any],
) -> None:
    first = create(client, arrived)
    with transaction(settings.database_url) as repo:
        # Only isolated synthetic verification cooldown is advanced.
        repo.execute("UPDATE contact_verification SET created_at=now()-interval '2 minutes'")
    client.cookies.clear()
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    receipt = verify(client, thread, csrf, draft)
    second = client.post(
        f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm",
        headers=csrf,
        json=confirmation(draft, receipt),
    ).json()
    headers = staff_headers(client, "demo-operator")
    prefix = f"/api/stores/{STORE}/appointments/{second['id']}"
    assert client.post(prefix + "/decision", headers=headers, json=decision()).status_code == 200
    assert (
        client.post(
            prefix + "/arrive",
            headers=headers,
            json={
                "request_key": str(uuid4()),
                "expected_version": 2,
                "accepted": True,
                "identity_checked": True,
            },
        ).status_code
        == 200
    )
    second_row = create(client, {**arrived, "id": second["id"]})
    assert second_row["id"] != first["id"] and second_row["phone_masked"] == first["phone_masked"]
    assert client.get(customer_url(arrived)).status_code == 404
    assert (
        client.get(f"/api/threads/{thread}/appointments/{second['id']}/consultation").json()["id"]
        == second_row["id"]
    )
    assert client.get(BASE, headers=arrived["consultant"]).json()["total"] == 2
