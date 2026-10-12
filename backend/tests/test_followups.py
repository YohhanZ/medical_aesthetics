"""Persistent follow-up invitations and local feedback, using isolated PostgreSQL only."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import PostgresRepository, transaction
from app.domain import Actor, DomainError, now
from app.followups import (
    CUSTOMER_TEXT,
    FollowupCreate,
    FollowupResponse,
    Followups,
    FollowupStaffAction,
)
from app.seed import CONSULTANT, OTHER_STORE, STORE
from app.services import IdentityService
from tests.conftest import staff_headers, visitor_headers
from tests.test_booking_lifecycle import booking as booking
from tests.test_consultation_cases import BASE as CASES
from tests.test_consultation_cases import arrived as arrived
from tests.test_consultation_cases import confirm_body, create, customer_url, revision

BASE = f"/api/stores/{STORE}/followups"


@pytest.fixture
def case(client: TestClient, arrived: dict[str, Any]) -> dict[str, Any]:
    original = create(client, arrived)
    options = client.get(
        f"/api/stores/{STORE}/consultation-options", headers=arrived["consultant"]
    ).json()["items"]
    updated = client.post(
        f"{CASES}/{original['id']}/revisions",
        headers=arrived["consultant"],
        json=revision(project_version_id=options[0]["id"]),
    )
    assert updated.status_code == 200, updated.text
    response = client.post(
        customer_url(arrived) + "/decision",
        headers=arrived["csrf"],
        json=confirm_body(updated.json()),
    )
    assert response.status_code == 200, response.text
    return {**arrived, "case": response.json()}


def plan(case: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "case_id": case["case"]["id"],
        "expected_case_version": case["case"]["version"],
        "request_key": str(uuid4()),
        "accepted": True,
        "due_at": (now() + timedelta(days=1)).isoformat(),
        "message": "了解咨询后是否还有疑问，可以在这里反馈",
        **changes,
    }


def propose(client: TestClient, case: dict[str, Any]) -> dict[str, Any]:
    result = client.post(BASE, headers=case["consultant"], json=plan(case))
    assert result.status_code == 200, result.text
    return dict(result.json())


def url(case: dict[str, Any], task: dict[str, Any] | None = None) -> str:
    root = f"/api/threads/{case['thread']}/appointments/{case['id']}/followups"
    return root if task is None else root + f"/{task['id']}/response"


def respond(row: dict[str, Any], action: str = "accept", **changes: Any) -> dict[str, Any]:
    return {
        "request_key": str(uuid4()),
        "accepted": True,
        "expected_version": row["version"],
        "snapshot_hash": row["snapshot_hash"],
        "action": action,
        "confirmation_text": CUSTOMER_TEXT[action],
        **changes,
    }


def staff_action(row: dict[str, Any], action: str = "note") -> dict[str, Any]:
    return {
        "request_key": str(uuid4()),
        "accepted": True,
        "expected_version": row["version"],
        "action": action,
        "note": "仅供门店内部的合成跟进记录",
    }


def test_followup_confirmation_private_notes_feedback_and_replay(
    client: TestClient, settings: Settings, case: dict[str, Any]
) -> None:
    body = plan(case)
    row = client.post(BASE, headers=case["consultant"], json=body).json()
    assert row["state"] == "awaiting_confirmation" and row["channel"] == "in_app"
    assert client.post(BASE, headers=case["consultant"], json=body).json() == row
    assert (
        client.get(f"/api/stores/{STORE}/followup-cases", headers=case["consultant"]).json()[
            "total"
        ]
        == 1
    )
    accepted = client.post(url(case, row), headers=case["csrf"], json=respond(row))
    assert accepted.status_code == 200 and accepted.json()["state"] == "scheduled"
    row = accepted.json()
    noted = client.post(
        f"{BASE}/{row['id']}/actions", headers=case["consultant"], json=staff_action(row)
    )
    assert noted.status_code == 200 and noted.json()["state"] == "scheduled"
    assert noted.json()["history"][-1]["text"] == "仅供门店内部的合成跟进记录"
    customer = client.get(url(case)).json()["items"][0]
    assert customer["version"] == 3 and all(e["kind"] != "note" for e in customer["history"])
    assert "仅供门店内部" not in str(customer) and "phone_masked" not in customer
    feedback = respond(customer, "feedback", result="need_help", feedback="还有流程方面的问题")
    completed = client.post(url(case, row), headers=case["csrf"], json=feedback)
    assert completed.status_code == 200 and completed.json()["state"] == "completed"
    assert completed.json()["history"][-1]["result"] == "need_help"
    assert (
        client.post(url(case, row), headers=case["csrf"], json=feedback).json() == completed.json()
    )
    assert client.post(BASE, headers=case["consultant"], json=body).json()["state"] == "completed"
    assert (
        client.post(
            BASE, headers=case["consultant"], json={**body, "message": "改变原请求"}
        ).status_code
        == 409
    )
    queue = client.get(BASE + "?state=completed&limit=1", headers=case["consultant"]).json()
    assert queue["total"] == 1 and queue["counts"] == {"completed": 1}
    assert client.get(BASE + "?offset=1", headers=case["consultant"]).json()["items"] == []
    with transaction(settings.database_url) as repo:
        events = repo.all("SELECT * FROM followup_event ORDER BY version")
        assert len(events) == 4 and events[-1]["method"] == "customer_button"
        assert "还有流程" not in str(events) and "19900000001" not in str(events)
        assert "仅供门店内部" not in str(repo.all("SELECT * FROM audit"))


@pytest.mark.parametrize("action", ["reject", "cancel"])
def test_customer_pause_blocks_new_invitations_until_explicit_resume(
    client: TestClient, case: dict[str, Any], action: str
) -> None:
    row = propose(client, case)
    if action == "cancel":
        row = client.post(url(case, row), headers=case["csrf"], json=respond(row)).json()
    declined = client.post(url(case, row), headers=case["csrf"], json=respond(row, action))
    assert declined.status_code == 200 and declined.json()["opted_out"]
    assert (
        client.post(BASE, headers=case["consultant"], json=plan(case)).json()["code"]
        == "followup_opted_out"
    )
    row = declined.json()
    resumed = client.post(url(case, row), headers=case["csrf"], json=respond(row, "resume"))
    assert resumed.status_code == 200 and not resumed.json()["opted_out"]
    second = propose(client, case)
    assert second["id"] != row["id"] and second["state"] == "awaiting_confirmation"


@pytest.mark.parametrize(
    "mutation", ["version", "hash", "ack", "text", "author", "source", "expired", "project"]
)
def test_invalid_acceptance_creates_no_customer_event(
    client: TestClient, settings: Settings, case: dict[str, Any], mutation: str
) -> None:
    row = propose(client, case)
    body = respond(row)
    if mutation == "version":
        body["expected_version"] += 1
    elif mutation == "hash":
        body["snapshot_hash"] = "0" * 64
    elif mutation == "ack":
        body["accepted"] = False
    elif mutation == "text":
        body["confirmation_text"] = "同意治疗"
    elif mutation == "source":
        result = client.post(
            f"{CASES}/{case['case']['id']}/revisions", headers=case["consultant"], json=revision(2)
        )
        assert result.status_code == 200
    else:
        with transaction(settings.database_url) as repo:
            if mutation == "author":
                repo.execute(
                    "DELETE FROM store_grant WHERE staff_id=%s AND permission='customer_manage'",
                    (CONSULTANT,),
                )
            elif mutation == "expired":
                repo.execute(
                    "UPDATE followup_task SET due_at=now()-interval '1 minute' WHERE id=%s",
                    (row["id"],),
                )
            elif mutation == "project":
                repo.execute(
                    "UPDATE knowledge_version SET status='withdrawn' WHERE id=%s",
                    (case["case"]["current"]["project_version_id"],),
                )
    result = client.post(url(case, row), headers=case["csrf"], json=body)
    assert result.status_code in (409, 422, 404), result.text
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM followup_event") == {"n": 1}
        assert repo.one("SELECT state FROM followup_task") == {"state": "awaiting_confirmation"}
    # Withdrawal/expiry must not prevent a customer from declining and pausing.
    assert (
        client.post(url(case, row), headers=case["csrf"], json=respond(row, "reject")).status_code
        == 200
    )


def test_followup_scope_roles_csrf_and_read_only(
    client: TestClient, settings: Settings, case: dict[str, Any]
) -> None:
    row = propose(client, case)
    assert client.post(url(case, row), json=respond(row)).status_code == 403
    wrong = url({**case, "thread": str(uuid4())}, row)
    assert client.post(wrong, headers=case["csrf"], json=respond(row)).status_code == 404
    wrong = url({**case, "id": str(uuid4())}, row)
    assert client.post(wrong, headers=case["csrf"], json=respond(row)).status_code == 404
    for account in ("demo-operator", "demo-author", "demo-platform-admin"):
        assert client.get(BASE, headers=staff_headers(client, account)).status_code == 403
    assert (
        client.get(BASE.replace(STORE, OTHER_STORE), headers=case["consultant"]).status_code == 403
    )
    with transaction(settings.database_url) as repo:
        repo.execute(
            "DELETE FROM store_grant WHERE staff_id=%s AND permission='customer_manage'",
            (CONSULTANT,),
        )
    assert client.get(BASE, headers=case["consultant"]).status_code == 200
    assert (
        client.post(
            f"{BASE}/{row['id']}/actions", headers=case["consultant"], json=staff_action(row)
        ).status_code
        == 403
    )
    client.cookies.clear()
    csrf = visitor_headers(client)
    assert client.get(url(case)).status_code == 404
    assert client.post(url(case, row), headers=csrf, json=respond(row)).status_code == 404


def test_followup_creation_requires_confirmation_valid_plan_and_no_open_task(
    client: TestClient, case: dict[str, Any]
) -> None:
    for changes in (
        {"accepted": False},
        {"due_at": now().isoformat()},
        {"message": " "},
        {"expected_case_version": 99},
    ):
        assert client.post(
            BASE, headers=case["consultant"], json=plan(case, **changes)
        ).status_code in (409, 422)
    first = propose(client, case)
    assert (
        client.post(BASE, headers=case["consultant"], json=plan(case)).json()["code"]
        == "followup_already_open"
    )
    cancelled = client.post(
        f"{BASE}/{first['id']}/actions",
        headers=case["consultant"],
        json=staff_action(first, "cancel"),
    )
    assert cancelled.status_code == 200 and not cancelled.json()["opted_out"]
    assert propose(client, case)["id"] != first["id"]


def actors(client: TestClient, settings: Settings, case: dict[str, Any]) -> tuple[Actor, Actor]:
    with transaction(settings.database_url) as repo:
        identity = IdentityService(repo, settings)
        staff = identity.authenticate(case["consultant"]["Authorization"].split()[1], "staff")
        visitor = identity.authenticate(
            client.cookies.get("ma_visitor", ""), "visitor", case["csrf"]["X-CSRF-Token"]
        )
    return staff, visitor


def test_followup_concurrent_creation_and_audit_rollback(
    client: TestClient, settings: Settings, case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = PostgresRepository.audit

    def fail(
        self: PostgresRepository, actor: Actor, action: str, resource: str, request_id: str
    ) -> None:
        if action == "followup.created":
            raise RuntimeError("synthetic audit failure")
        original(self, actor, action, resource, request_id)

    monkeypatch.setattr(PostgresRepository, "audit", fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        client.post(BASE, headers=case["consultant"], json=plan(case))
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM followup_task") == {"n": 0}
        assert repo.one("SELECT count(*) AS n FROM followup_command") == {"n": 0}
    monkeypatch.setattr(PostgresRepository, "audit", original)
    staff, _ = actors(client, settings, case)
    data = FollowupCreate(**plan(case))

    def write(_: int) -> str:
        with transaction(settings.database_url) as repo:
            return str(Followups(repo, settings, staff, STORE).create(data, str(uuid4()))["id"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(write, range(2)))) == 1
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM followup_event") == {"n": 1}


def test_accept_and_staff_cancel_race_replays_never_restore_state(
    client: TestClient, settings: Settings, case: dict[str, Any]
) -> None:
    row = propose(client, case)
    staff, visitor = actors(client, settings, case)
    accept = FollowupResponse(**respond(row))
    cancel = FollowupStaffAction(**staff_action(row, "cancel"))

    def write(kind: str) -> int:
        try:
            with transaction(settings.database_url) as repo:
                if kind == "accept":
                    Followups(repo, settings, visitor, STORE, case["thread"], case["id"]).respond(
                        row["id"], accept, str(uuid4())
                    )
                else:
                    Followups(repo, settings, staff, STORE).staff_action(
                        row["id"], cancel, str(uuid4())
                    )
            return 200
        except DomainError as error:
            return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, ["accept", "cancel"])) == [200, 409]
    current = client.get(BASE + f"/{row['id']}", headers=case["consultant"]).json()
    if current["state"] == "scheduled":
        assert (
            client.post(
                url(case, row), headers=case["csrf"], json=accept.model_dump(mode="json")
            ).json()["version"]
            == 2
        )
    else:
        assert current["state"] == "cancelled"
        assert (
            client.post(
                f"{BASE}/{row['id']}/actions",
                headers=case["consultant"],
                json=cancel.model_dump(mode="json"),
            ).json()["state"]
            == "cancelled"
        )
