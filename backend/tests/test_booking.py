"""Real isolated PostgreSQL booking transactions; no real SMS or customer data."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.booking import BookingApplication, BookingService
from app.booking_models import CONFIRMATION_TEXT, ConfirmInput
from app.config import Settings
from app.db import PostgresRepository, transaction
from app.domain import Actor, DomainError, now
from app.services import IdentityService
from app.sms_gateway import Delivery
from tests.conftest import visitor_headers
from tests.test_customer_catalog import publish_catalog


@pytest.fixture(autouse=True)
def approved_policy(settings: Settings) -> None:
    publish_catalog(settings)


def ready(client: TestClient) -> tuple[str, dict[str, str], str]:
    csrf = visitor_headers(client)
    thread = client.post("/api/threads", headers=csrf).json()["thread_id"]
    run = client.post(
        f"/api/threads/{thread}/messages",
        headers=csrf,
        json={"message_id": str(uuid4()), "question": "我想预约到店咨询"},
    ).json()["run_id"]
    return thread, csrf, run


def create_draft(
    client: TestClient, thread: str, csrf: dict[str, str], run: str, **changes: Any
) -> dict[str, Any]:
    data = {
        "request_key": str(uuid4()),
        "trigger_run_id": run,
        "name": "合成访客",
        "phone": "19900000001",
        "desired_at": (now() + timedelta(days=2)).isoformat(),
        "intention": "不确定项目，先咨询",
        **changes,
    }
    result = client.post(f"/api/threads/{thread}/appointment-drafts", headers=csrf, json=data)
    assert result.status_code == 201, result.text
    return result.json()


def verify(
    client: TestClient, thread: str, csrf: dict[str, str], draft: dict[str, Any]
) -> dict[str, Any]:
    response = client.post(
        f"/api/threads/{thread}/appointment-drafts/{draft['id']}/verification",
        headers=csrf,
        json={"request_key": str(uuid4()), "sms_consent": True},
    )
    assert response.status_code == 200, response.text
    receipt = response.json()
    result = client.post(
        f"/api/threads/{thread}/contact-verifications/{receipt['id']}/verify",
        headers=csrf,
        json={"code": receipt["simulated_code"]},
    )
    assert result.status_code == 200 and result.json()["verified"], result.text
    return receipt


def confirmation(draft: dict[str, Any], receipt: dict[str, Any], **changes: Any) -> dict[str, Any]:
    return {
        "request_key": str(uuid4()),
        "snapshot_hash": draft["snapshot_hash"],
        "verification_id": receipt["id"],
        "accepted": True,
        "confirmation_text": CONFIRMATION_TEXT,
        **changes,
    }


def test_booking_confirmation_replay_reload_and_encrypted_records(
    client: TestClient, settings: Settings
) -> None:
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    assert draft["phone_masked"] == "199****0001" and draft["simulated"]
    receipt = verify(client, thread, csrf, draft)
    payload = confirmation(draft, receipt)
    url = f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm"
    result = client.post(url, headers=csrf, json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "pending_store_confirmation"
    assert client.post(url, headers=csrf, json=payload).json() == result.json()
    assert (
        client.post(url, headers=csrf, json={**payload, "snapshot_hash": "0" * 64}).status_code
        == 409
    )
    state = client.get(f"/api/threads/{thread}/booking").json()
    assert state["draft"] is None and state["trigger_run_id"] is None
    assert state["appointments"] == [result.json()]
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM appointment") == {"n": 1}
        assert repo.one("SELECT count(*) AS n FROM booking_outbox") == {"n": 1}
        row = repo.one("SELECT * FROM appointment_confirmation")
        assert row and row["confirmed_at"] and row["method"] == "customer_button"
        assert row["evidence_request_id"] and row["snapshot_hash"] == draft["snapshot_hash"]
        assert "19900000001" not in str(row) and "合成访客" not in str(row)
        for table in (
            "agent_message",
            "agent_checkpoint",
            "agent_trace",
            "audit",
            "booking_idempotency",
        ):
            assert "19900000001" not in str(repo.all(f"SELECT * FROM {table}"))
    assert (
        client.post(
            f"/api/threads/{thread}/appointment-drafts",
            headers=csrf,
            json={
                "request_key": str(uuid4()),
                "trigger_run_id": run,
                "name": "合成",
                "phone": "19900000001",
                "desired_at": (now() + timedelta(days=3)).isoformat(),
                "intention": "先咨询",
            },
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "change",
    [{"accepted": False}, {"confirmation_text": "已预约成功"}, {"snapshot_hash": "0" * 64}],
)
def test_missing_or_changed_confirmation_never_writes(
    client: TestClient, settings: Settings, change: dict[str, Any]
) -> None:
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    receipt = verify(client, thread, csrf, draft)
    result = client.post(
        f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm",
        headers=csrf,
        json=confirmation(draft, receipt, **change),
    )
    assert result.status_code in (409, 422)
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM appointment_confirmation") == {"n": 0}
        assert repo.one("SELECT count(*) AS n FROM appointment") == {"n": 0}


def test_unverified_contact_attempts_lock_and_sms_consent(
    client: TestClient, settings: Settings
) -> None:
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    url = f"/api/threads/{thread}/appointment-drafts/{draft['id']}/verification"
    assert (
        client.post(
            url, headers=csrf, json={"request_key": str(uuid4()), "sms_consent": False}
        ).status_code
        == 422
    )
    data = {"request_key": str(uuid4()), "sms_consent": True}
    receipt = client.post(url, headers=csrf, json=data).json()
    assert client.post(url, headers=csrf, json=data).json() == receipt
    assert (
        client.post(url, headers=csrf, json={**data, "request_key": str(uuid4())}).status_code
        == 429
    )
    assert (
        client.post(
            f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm",
            headers=csrf,
            json=confirmation(draft, receipt),
        ).status_code
        == 409
    )
    verify_url = f"/api/threads/{thread}/contact-verifications/{receipt['id']}/verify"
    wrong = "000000" if receipt["simulated_code"] != "000000" else "111111"
    for _ in range(5):
        assert client.post(verify_url, headers=csrf, json={"code": wrong}).status_code == 422
    assert (
        client.post(verify_url, headers=csrf, json={"code": receipt["simulated_code"]}).json()[
            "code"
        ]
        == "verification_expired_or_locked"
    )
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT attempts FROM contact_verification") == {"attempts": 5}


@pytest.mark.parametrize("question", ["先不预约", "我皮肤发痒怎么办"])
def test_new_decline_or_medical_turn_invalidates_old_draft(
    client: TestClient, settings: Settings, question: str
) -> None:
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    receipt = verify(client, thread, csrf, draft)
    client.post(
        f"/api/threads/{thread}/messages",
        headers=csrf,
        json={"message_id": str(uuid4()), "question": question},
    )
    assert (
        client.get(f"/api/threads/{thread}/booking").json()["blocked_reason"]
        == "booking_offer_changed"
    )
    assert (
        client.post(
            f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm",
            headers=csrf,
            json=confirmation(draft, receipt),
        ).status_code
        == 409
    )
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM appointment") == {"n": 0}


def test_draft_edit_expiry_and_expired_verification(client: TestClient, settings: Settings) -> None:
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    receipt = verify(client, thread, csrf, draft)
    edited = create_draft(client, thread, csrf, run, intention="补水方向咨询", phone="19900000002")
    assert (
        client.post(
            f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm",
            headers=csrf,
            json=confirmation(draft, receipt),
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/threads/{thread}/appointment-drafts/{edited['id']}/confirm",
            headers=csrf,
            json=confirmation(edited, receipt),
        ).status_code
        == 409
    )
    with transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE appointment_draft SET expires_at=now()-interval '1 second' WHERE id=%s",
            (edited["id"],),
        )
    assert (
        client.get(f"/api/threads/{thread}/booking").json()["blocked_reason"]
        == "draft_expired_or_replaced"
    )


def test_cross_visitor_store_thread_csrf_and_no_unprompted_booking(
    client: TestClient, settings: Settings
) -> None:
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    receipt = verify(client, thread, csrf, draft)
    url = f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm"
    assert client.post(url, json=confirmation(draft, receipt)).status_code == 403
    for store in ("demo-shanghai", "demo-hangzhou"):
        with TestClient(create_app(settings)) as other:
            other_csrf = visitor_headers(other, store)
            assert other.get(f"/api/threads/{thread}/booking").status_code == 404
            assert (
                other.post(url, headers=other_csrf, json=confirmation(draft, receipt)).status_code
                == 404
            )
    new_thread = client.post("/api/threads", headers=csrf).json()["thread_id"]
    assert (
        client.post(
            f"/api/threads/{new_thread}/appointment-drafts/{draft['id']}/confirm",
            headers=csrf,
            json=confirmation(draft, receipt),
        ).status_code
        == 404
    )
    client.post("/api/visitor-sessions/logout", headers=csrf)
    assert client.get(f"/api/threads/{thread}/booking").status_code == 401


def test_submission_audit_failure_rolls_back_everything(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    receipt = verify(client, thread, csrf, draft)
    original = PostgresRepository.audit

    def fail(
        self: PostgresRepository, actor: Actor, action: str, resource: str, request_id: str
    ) -> None:
        if action == "appointment.submit":
            raise DomainError("test_audit_failure", 503)
        original(self, actor, action, resource, request_id)

    monkeypatch.setattr(PostgresRepository, "audit", fail)
    payload = confirmation(draft, receipt)
    result = client.post(
        f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm",
        headers=csrf,
        json=payload,
    )
    assert result.status_code == 503
    with transaction(settings.database_url) as repo:
        for table in ("appointment", "appointment_confirmation", "booking_outbox"):
            assert repo.one(f"SELECT count(*) AS n FROM {table}") == {"n": 0}
        assert repo.one("SELECT consumed_at FROM contact_verification")["consumed_at"] is None
    monkeypatch.setattr(PostgresRepository, "audit", original)
    assert (
        client.post(
            f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm",
            headers=csrf,
            json=payload,
        ).status_code
        == 200
    )


def test_unknown_sms_not_resent_after_error_or_process_recreation(
    client: TestClient, settings: Settings
) -> None:
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)

    class UnknownSms:
        calls = 0

        def send(self, phone: str, code: str, reference: str) -> Delivery:
            self.calls += 1
            return Delivery("unknown")

    gateway = UnknownSms()
    client.app.state.booking_sms_gateway = gateway
    data = {"request_key": str(uuid4()), "sms_consent": True}
    url = f"/api/threads/{thread}/appointment-drafts/{draft['id']}/verification"
    result = client.post(url, headers=csrf, json=data).json()
    assert result["delivery_state"] == "unknown" and "simulated_code" not in result
    assert client.post(url, headers=csrf, json=data).json() == result
    assert (
        client.post(url, headers=csrf, json={**data, "request_key": str(uuid4())}).json()["code"]
        == "verification_delivery_unknown"
    )
    assert gateway.calls == 1
    with transaction(settings.database_url) as repo:
        actor = IdentityService(repo, settings).authenticate(
            client.cookies["ma_visitor"], "visitor"
        )
    assert (
        BookingApplication(settings, gateway).send_code(
            actor, thread, draft["id"], data["request_key"], True, str(uuid4())
        )
        == result
    )
    assert gateway.calls == 1


def test_concurrent_confirm_only_one_transaction(client: TestClient, settings: Settings) -> None:
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    receipt = verify(client, thread, csrf, draft)
    payload = ConfirmInput.model_validate(confirmation(draft, receipt))
    with transaction(settings.database_url) as repo:
        actor = IdentityService(repo, settings).authenticate(
            client.cookies["ma_visitor"], "visitor"
        )

    def submit() -> dict[str, Any]:
        with transaction(settings.database_url) as repo:
            return BookingService(repo, settings, actor, thread).confirm(
                draft["id"], payload, str(uuid4())
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: submit(), range(2)))
    assert rows[0] == rows[1]
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM appointment") == {"n": 1}


def test_project_withdrawal_blocks_confirm(client: TestClient, settings: Settings) -> None:
    publish_catalog(settings)
    thread, csrf, run = ready(client)
    project = client.get("/api/catalog/projects").json()["items"][0]
    draft = create_draft(client, thread, csrf, run, project_version_id=project["id"])
    receipt = verify(client, thread, csrf, draft)
    with transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE knowledge_version SET status='withdrawn' WHERE id=%s", (project["id"],)
        )
    assert (
        client.post(
            f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm",
            headers=csrf,
            json=confirmation(draft, receipt),
        ).status_code
        == 404
    )


def test_policy_withdrawal_and_expired_verified_receipt_block_submission(
    client: TestClient, settings: Settings
) -> None:
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    receipt = verify(client, thread, csrf, draft)
    url = f"/api/threads/{thread}/appointment-drafts/{draft['id']}/confirm"
    with transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE contact_verification SET verified_until=now()-interval '1 second' WHERE id=%s",
            (receipt["id"],),
        )
    assert (
        client.post(url, headers=csrf, json=confirmation(draft, receipt)).json()["code"]
        == "contact_verification_required"
    )
    with transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE contact_verification SET verified_until=now()+interval '5 minutes' WHERE id=%s",
            (receipt["id"],),
        )
        repo.execute(
            "UPDATE knowledge_version SET status='withdrawn' WHERE id=%s", (draft["policy"]["id"],)
        )
    assert (
        client.post(url, headers=csrf, json=confirmation(draft, receipt)).json()["code"]
        == "booking_policy_unavailable"
    )
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM appointment") == {"n": 0}


def test_draft_same_key_replay_conflict_discard_and_invalid_time(
    client: TestClient, settings: Settings
) -> None:
    thread, csrf, run = ready(client)
    key = str(uuid4())
    date = (now() + timedelta(days=2)).isoformat()
    draft = create_draft(client, thread, csrf, run, request_key=key, desired_at=date)
    assert create_draft(client, thread, csrf, run, request_key=key, desired_at=date) == draft
    body = {
        "request_key": key,
        "trigger_run_id": run,
        "name": "合成访客",
        "phone": "19900000002",
        "desired_at": date,
        "intention": "先咨询",
    }
    url = f"/api/threads/{thread}/appointment-drafts"
    assert client.post(url, headers=csrf, json=body).json()["code"] == "booking_key_conflict"
    assert (
        client.post(
            url,
            headers=csrf,
            json={
                **body,
                "request_key": str(uuid4()),
                "desired_at": (now() - timedelta(hours=1)).isoformat(),
            },
        ).json()["code"]
        == "booking_time_invalid"
    )
    discard_url = f"{url}/{draft['id']}/discard"
    assert client.post(discard_url, headers=csrf).json() == {"discarded": True}
    assert client.post(discard_url, headers=csrf).json() == {"discarded": True}
    assert client.get(f"/api/threads/{thread}/booking").json()["draft"] is None


def test_foreign_trigger_and_expired_sms_never_approve(
    client: TestClient, settings: Settings
) -> None:
    thread, csrf, run = ready(client)
    draft = create_draft(client, thread, csrf, run)
    response = client.post(
        f"/api/threads/{thread}/appointment-drafts/{draft['id']}/verification",
        headers=csrf,
        json={"request_key": str(uuid4()), "sms_consent": True},
    )
    receipt = response.json()
    with transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE contact_verification SET expires_at=now()-interval '1 second' WHERE id=%s",
            (receipt["id"],),
        )
    assert (
        client.post(
            f"/api/threads/{thread}/contact-verifications/{receipt['id']}/verify",
            headers=csrf,
            json={"code": receipt["simulated_code"]},
        ).json()["code"]
        == "verification_expired_or_locked"
    )
    body = {
        "request_key": str(uuid4()),
        "trigger_run_id": str(uuid4()),
        "name": "合成",
        "phone": "19900000001",
        "desired_at": (now() + timedelta(days=2)).isoformat(),
        "intention": "先咨询",
    }
    assert (
        client.post(f"/api/threads/{thread}/appointment-drafts", headers=csrf, json=body).json()[
            "code"
        ]
        == "booking_offer_changed"
    )
