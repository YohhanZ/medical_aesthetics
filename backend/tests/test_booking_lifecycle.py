"""Consent, stale proposals, scoped access and concurrent lifecycle writes in real test PG."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.booking_lifecycle import (
    ACCEPT_CHANGE_TEXT,
    CANCEL_TEXT,
    REJECT_CHANGE_TEXT,
    BookingLifecycle,
    CancelInput,
    RespondInput,
)
from app.config import Settings
from app.db import PostgresRepository, transaction
from app.domain import DomainError, now
from app.seed import OPERATOR, OTHER_STORE, STORE
from app.services import IdentityService
from tests.conftest import staff_headers, visitor_headers
from tests.test_booking import confirmation, create_draft, ready, verify
from tests.test_customer_catalog import publish_catalog
from tests.test_staff_booking import decision

BASE = f"/api/stores/{STORE}/appointments"


@pytest.fixture
def booking(client: TestClient, settings: Settings) -> dict[str, Any]:
    publish_catalog(settings)
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    receipt = verify(client, thread, csrf, draft)
    response = client.post(
        f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm",
        headers=csrf,
        json=confirmation(draft, receipt),
    )
    assert response.status_code == 200, response.text
    return {
        "id": response.json()["id"],
        "thread": thread,
        "csrf": csrf,
        "staff": staff_headers(client, "demo-operator"),
        "original": response.json(),
    }


def change(**changes: Any) -> dict[str, Any]:
    return {
        "request_key": str(uuid4()),
        "expected_version": 1,
        "accepted": True,
        "availability_checked": True,
        "proposed_at": (now() + timedelta(days=3)).isoformat(),
        **changes,
    }


def propose(client: TestClient, booking: dict[str, Any], **changes: Any) -> dict[str, Any]:
    response = client.post(
        f"{BASE}/{booking['id']}/change-proposals", headers=booking["staff"], json=change(**changes)
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def response_body(row: dict[str, Any], **changes: Any) -> dict[str, Any]:
    proposal = row["change_proposal"]
    return {
        "request_key": str(uuid4()),
        "expected_version": row["version"],
        "accepted": True,
        "proposal_id": proposal["id"],
        "snapshot_hash": proposal["snapshot_hash"],
        "decision": "accept",
        "confirmation_text": ACCEPT_CHANGE_TEXT,
        **changes,
    }


def customer_url(booking: dict[str, Any], action: str) -> str:
    return f"/api/threads/{booking['thread']}/appointments/{booking['id']}/{action}"


def test_accept_and_arrive_preserve_original_and_replay(
    client: TestClient,
    settings: Settings,
    booking: dict[str, Any],
) -> None:
    proposed = propose(client, booking)
    assert proposed["state"] == "pending_store_confirmation" and proposed["confirmed_at"] is None
    assert proposed["desired_at"] == booking["original"]["desired_at"]
    assert (
        client.post(
            f"{BASE}/{booking['id']}/decision",
            headers=booking["staff"],
            json=decision(expected_version=2),
        ).status_code
        == 409
    )
    body = response_body(proposed)
    url = customer_url(booking, "change-response")
    accepted = client.post(url, headers=booking["csrf"], json=body)
    assert accepted.status_code == 200, accepted.text
    row = accepted.json()
    assert row["version"] == 3 and row["state"] == "confirmed" and not row["change_proposal"]
    assert datetime.fromisoformat(row["confirmed_at"]) == datetime.fromisoformat(
        proposed["change_proposal"]["proposed_at"]
    )
    assert client.post(url, headers=booking["csrf"], json=body).json() == row
    arrival = {
        "request_key": str(uuid4()),
        "expected_version": 3,
        "accepted": True,
        "identity_checked": True,
    }
    arrival_url = f"{BASE}/{booking['id']}/arrive"
    arrived = client.post(arrival_url, headers=booking["staff"], json=arrival)
    assert arrived.status_code == 200, arrived.text
    assert arrived.json()["arrived_at"] and arrived.json()["version"] == 4
    assert client.post(arrival_url, headers=booking["staff"], json=arrival).json() == arrived.json()
    # Replaying an older accepted command returns current authority, never reverts arrival.
    assert client.post(url, headers=booking["csrf"], json=body).json()["state"] == "arrived"
    assert client.get(BASE + "?state=arrived", headers=booking["staff"]).json()["total"] == 1
    with transaction(settings.database_url) as repo:
        records = repo.all("SELECT * FROM booking_action_confirmation ORDER BY confirmed_at")
        assert [r["operation"] for r in records] == [
            "change_proposed",
            "change_accepted",
            "arrived",
        ]
        assert records[1]["method"] == "customer_button" and records[1]["evidence_request_id"]
        assert "19900000001" not in str(records) and "19900000001" not in str(
            repo.all("SELECT * FROM audit")
        )
        assert repo.one("SELECT count(*) AS n FROM appointment_confirmation") == {"n": 1}


@pytest.mark.parametrize("confirmed", [False, True])
def test_reject_keeps_original_arrangement(
    client: TestClient, booking: dict[str, Any], confirmed: bool
) -> None:
    version = 1
    if confirmed:
        assert (
            client.post(
                f"{BASE}/{booking['id']}/decision", headers=booking["staff"], json=decision()
            ).status_code
            == 200
        )
        version = 2
    proposed = propose(client, booking, expected_version=version)
    body = response_body(proposed, decision="reject", confirmation_text=REJECT_CHANGE_TEXT)
    response = client.post(
        customer_url(booking, "change-response"), headers=booking["csrf"], json=body
    )
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["state"] == ("confirmed" if confirmed else "pending_store_confirmation")
    assert row["desired_at"] == booking["original"]["desired_at"] and row["change_proposal"] is None
    if confirmed:
        assert datetime.fromisoformat(row["confirmed_at"]) == datetime.fromisoformat(
            row["desired_at"]
        )


@pytest.mark.parametrize(
    "mutation", ["expiry", "superseded", "hash", "policy", "grant", "confirmation"]
)
def test_invalid_proposal_cannot_change_time(
    client: TestClient,
    settings: Settings,
    booking: dict[str, Any],
    mutation: str,
) -> None:
    proposed = propose(client, booking)
    body = response_body(proposed)
    if mutation == "superseded":
        propose(client, booking, expected_version=2)
    elif mutation in ("expiry", "policy", "grant"):
        with transaction(settings.database_url) as repo:
            if mutation == "expiry":
                repo.execute(
                    "UPDATE booking_change_proposal SET expires_at=now()-interval '1 second'"
                )
            elif mutation == "policy":
                repo.execute(
                    "UPDATE knowledge_version SET status='withdrawn' "
                    "WHERE knowledge_key='faq-online-application'"
                )
            else:
                repo.execute(
                    "DELETE FROM store_grant WHERE staff_id=%s AND permission='appointment_manage'",
                    (OPERATOR,),
                )
    elif mutation == "hash":
        body["snapshot_hash"] = "0" * 64
    else:
        body["accepted"] = False
    result = client.post(
        customer_url(booking, "change-response"), headers=booking["csrf"], json=body
    )
    assert result.status_code in (409, 422), result.text
    with transaction(settings.database_url) as repo:
        row = repo.one("SELECT state,confirmed_at FROM appointment WHERE id=%s", (booking["id"],))
        assert row == {"state": "pending_store_confirmation", "confirmed_at": None}
        assert repo.one(
            "SELECT count(*) AS n FROM booking_action_confirmation "
            "WHERE operation='change_accepted'"
        ) == {"n": 0}


@pytest.mark.parametrize("confirmed", [False, True])
def test_customer_cancellation_replays_and_invalidates_proposal(
    client: TestClient,
    booking: dict[str, Any],
    confirmed: bool,
) -> None:
    version = 1
    if confirmed:
        client.post(f"{BASE}/{booking['id']}/decision", headers=booking["staff"], json=decision())
        version = 2
    proposed = propose(client, booking, expected_version=version)
    body = {
        "request_key": str(uuid4()),
        "expected_version": version + 1,
        "accepted": True,
        "confirmation_text": CANCEL_TEXT,
    }
    url = customer_url(booking, "cancel")
    assert (
        client.post(url, headers=booking["csrf"], json={**body, "accepted": False}).status_code
        == 422
    )
    cancelled = client.post(url, headers=booking["csrf"], json=body)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled" and cancelled.json()["change_proposal"] is None
    assert client.post(url, headers=booking["csrf"], json=body).json() == cancelled.json()
    assert (
        client.post(
            url, headers=booking["csrf"], json={**body, "confirmation_text": "changed"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            customer_url(booking, "change-response"),
            headers=booking["csrf"],
            json=response_body(proposed),
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{BASE}/{booking['id']}/arrive",
            headers=booking["staff"],
            json={
                "request_key": str(uuid4()),
                "expected_version": version + 2,
                "accepted": True,
                "identity_checked": True,
            },
        ).status_code
        == 409
    )


def test_scopes_csrf_and_no_implicit_staff_role(
    client: TestClient, booking: dict[str, Any]
) -> None:
    body = {
        "request_key": str(uuid4()),
        "expected_version": 1,
        "accepted": True,
        "confirmation_text": CANCEL_TEXT,
    }
    assert client.post(customer_url(booking, "cancel"), json=body).status_code == 403
    original_cookies = dict(client.cookies)
    client.cookies.clear()
    csrf = visitor_headers(client)
    other_thread = client.post("/api/threads", headers=csrf).json()["thread_id"]
    assert client.post(customer_url(booking, "cancel"), headers=csrf, json=body).status_code == 404
    assert (
        client.post(
            f"/api/threads/{other_thread}/appointments/{booking['id']}/cancel",
            headers=csrf,
            json=body,
        ).status_code
        == 404
    )
    client.cookies.clear()
    client.cookies.update(original_cookies)
    for username in ("demo-author", "demo-platform-admin"):
        assert (
            client.post(
                f"{BASE}/{booking['id']}/change-proposals",
                headers=staff_headers(client, username),
                json=change(),
            ).status_code
            == 403
        )
    assert (
        client.post(
            f"/api/stores/{OTHER_STORE}/appointments/{booking['id']}/change-proposals",
            headers=booking["staff"],
            json=change(),
        ).status_code
        == 403
    )
    assert client.post(f"{BASE}/{booking['id']}/change-proposals", json=change()).status_code == 401


def test_arrival_requires_identity_and_customer_answer(
    client: TestClient, booking: dict[str, Any]
) -> None:
    client.post(f"{BASE}/{booking['id']}/decision", headers=booking["staff"], json=decision())
    body = {
        "request_key": str(uuid4()),
        "expected_version": 2,
        "accepted": True,
        "identity_checked": False,
    }
    url = f"{BASE}/{booking['id']}/arrive"
    assert client.post(url, headers=booking["staff"], json=body).status_code == 422
    proposed = propose(client, booking, expected_version=2)
    body.update(expected_version=3, identity_checked=True)
    assert client.post(url, headers=booking["staff"], json=body).status_code == 409
    client.post(
        customer_url(booking, "change-response"),
        headers=booking["csrf"],
        json=response_body(proposed, decision="reject", confirmation_text=REJECT_CHANGE_TEXT),
    )
    body.update(expected_version=4)
    assert client.post(url, headers=booking["staff"], json=body).status_code == 200
    assert (
        client.post(
            customer_url(booking, "cancel"),
            headers=booking["csrf"],
            json={
                "request_key": str(uuid4()),
                "expected_version": 5,
                "accepted": True,
                "confirmation_text": CANCEL_TEXT,
            },
        ).status_code
        == 409
    )


def test_atomic_rollback_and_cancel_accept_race(
    client: TestClient,
    settings: Settings,
    booking: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposed = propose(client, booking)
    with transaction(settings.database_url) as repo:
        actor = IdentityService(repo, settings).authenticate(
            client.cookies["ma_visitor"], "visitor", booking["csrf"]["X-CSRF-Token"]
        )
    cancel = CancelInput(
        request_key=uuid4(), expected_version=2, accepted=True, confirmation_text=CANCEL_TEXT
    )
    audit = PostgresRepository.audit

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(PostgresRepository, "audit", fail)
    with pytest.raises(RuntimeError), transaction(settings.database_url) as repo:
        BookingLifecycle(repo, settings, actor, STORE, booking["thread"]).cancel(
            booking["id"], cancel, str(uuid4())
        )
    monkeypatch.setattr(PostgresRepository, "audit", audit)
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT state,version FROM appointment") == {
            "state": "pending_store_confirmation",
            "version": 2,
        }
        assert repo.one("SELECT count(*) AS n FROM booking_action_confirmation") == {"n": 1}

    def write(operation: str) -> str:
        try:
            with transaction(settings.database_url) as repo:
                lifecycle = BookingLifecycle(repo, settings, actor, STORE, booking["thread"])
                if operation == "cancel":
                    lifecycle.cancel(booking["id"], cancel, str(uuid4()))
                else:
                    lifecycle.respond(
                        booking["id"], RespondInput(**response_body(proposed)), str(uuid4())
                    )
                return "success"
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, ["cancel", "accept"]))
    assert sorted(results) == ["appointment_state_conflict", "success"]
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT version FROM appointment") == {"version": 3}
        assert repo.one("SELECT count(*) AS n FROM booking_action_confirmation") == {"n": 2}
