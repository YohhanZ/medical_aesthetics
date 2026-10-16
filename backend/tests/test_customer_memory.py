"""Real PostgreSQL identity/consent/isolation tests; no external model or SMS calls."""

import os
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent_repository import PostgresAgentStore
from app.config import Settings
from app.consultation_agent import ConsultationAgent
from app.customer import PREFERENCES, CustomerService, extract_preferences
from app.db import transaction
from app.services import IdentityService
from tests.conftest import visitor_headers

PASSWORD = "Customer-test-only-2026!"


def register(client: TestClient, username: str = "alice") -> dict[str, str]:
    csrf = visitor_headers(client)
    result = client.post(
        "/api/customer-accounts",
        headers=csrf,
        json={
            "username": username,
            "password": PASSWORD,
            "bind_current": True,
            "enable_memory": True,
        },
    )
    assert result.status_code == 201, result.text
    return {"X-CSRF-Token": result.json()["csrf_token"]}


def message(client: TestClient, csrf: dict[str, str], thread: str, text: str) -> dict[str, Any]:
    result = client.post(
        f"/api/threads/{thread}/messages",
        headers=csrf,
        json={"message_id": str(uuid4()), "question": text},
    )
    assert result.status_code == 200, result.text
    return result.json()


def new_thread(client: TestClient, csrf: dict[str, str]) -> str:
    result = client.post("/api/threads", headers=csrf)
    assert result.status_code == 201, result.text
    return str(result.json()["thread_id"])


def enable(
    client: TestClient, csrf: dict[str, str], memory: bool = True, behavior: bool = True
) -> dict[str, Any]:
    result = client.post(
        "/api/customer/preferences",
        headers=csrf,
        json={"memory_enabled": memory, "behavior_enabled": behavior},
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_register_rotates_guest_credentials_and_preserves_history(
    client: TestClient,
    settings: Settings,
) -> None:
    csrf = visitor_headers(client)
    thread = new_thread(client, csrf)
    message(client, csrf, thread, "你好")
    old_cookie = client.cookies["ma_visitor"]
    result = client.post(
        "/api/customer-accounts",
        headers=csrf,
        json={
            "username": "Alice",
            "password": PASSWORD,
            "bind_current": True,
            "enable_memory": True,
        },
    )
    assert result.status_code == 201, result.text
    assert client.cookies["ma_visitor"] != old_cookie
    assert client.get(f"/api/threads/{thread}/messages").status_code == 200
    profile = client.get("/api/customer/me").json()
    assert profile["customer"] == {
        "username": "alice",
        "memory_enabled": True,
        "behavior_enabled": False,
    }
    with transaction(settings.database_url) as repo:
        row = repo.one("SELECT password_hash FROM customer_account")
        assert row and row["password_hash"].startswith("scrypt$")
        assert PASSWORD not in row["password_hash"]
    new_cookie = client.cookies["ma_visitor"]
    client.cookies.set("ma_visitor", old_cookie)
    assert client.get("/api/threads").status_code == 401
    client.cookies.set("ma_visitor", new_cookie)


def test_login_restores_identity_across_devices_without_importing_unrelated_guest(
    client: TestClient,
) -> None:
    csrf = register(client)
    original = client.get("/api/visitor-sessions/current").json()["visitor_id"]
    thread = new_thread(client, csrf)
    message(client, csrf, thread, "你好")
    client.cookies.clear()  # A second browser / expired credentials.
    guest_csrf = visitor_headers(client)
    guest_thread = new_thread(client, guest_csrf)
    login = client.post(
        "/api/customer-sessions",
        headers=guest_csrf,
        json={
            "username": "ALICE",
            "password": PASSWORD,
            "bind_current": False,
        },
    )
    assert login.status_code == 200, login.text
    assert login.json()["restored"] is True
    assert client.get("/api/visitor-sessions/current").json()["visitor_id"] == original
    assert client.get(f"/api/threads/{thread}/messages").status_code == 200
    assert client.get(f"/api/threads/{guest_thread}/messages").status_code == 404


def test_cross_thread_recall_update_forget_and_disable(client: TestClient) -> None:
    csrf = register(client)
    enable(client, csrf)
    thread = new_thread(client, csrf)
    message(client, csrf, thread, "我周末有空，我比较怕疼")
    profile = client.get("/api/customer/me").json()
    assert {r["key"] for r in profile["memories"]} == {"visit_time", "comfort"}
    next_thread = new_thread(client, csrf)
    recalled = message(client, csrf, next_thread, "你还记得我的偏好吗？")
    assert "周末方便到店" in recalled["answer"]
    assert "担心疼痛" in recalled["answer"]
    assert recalled["mode"] == "fixed" and not recalled["evidence_ids"]
    message(client, csrf, next_thread, "我现在不怕疼，我工作日有空")
    updated = client.get("/api/customer/me").json()["memories"]
    assert {r["value"] for r in updated} == {"不再担心疼痛", "工作日方便到店"}
    assert client.post("/api/customer/memories/comfort/forget", headers=csrf).status_code == 200
    result = message(client, csrf, new_thread(client, csrf), "我的偏好是什么？")
    assert "不再担心疼痛" not in result["answer"]
    enable(client, csrf, False, False)
    assert client.get("/api/customer/me").json()["memories"] == []
    enable(client, csrf)
    assert client.get("/api/customer/me").json()["memories"] == []


def test_thread_sidebar_titles_pagination_and_ownership(client: TestClient) -> None:
    csrf = register(client)
    original = new_thread(client, csrf)
    message(client, csrf, original, "我周末有空")
    recent = [new_thread(client, csrf) for _ in range(20)]
    first_page = client.get("/api/threads").json()["items"]
    assert len(first_page) == 20
    assert [row["thread_id"] for row in first_page] == list(reversed(recent))
    assert all(row["title"] == "新对话" for row in first_page)
    older = client.get("/api/threads?offset=20").json()["items"]
    assert len(older) == 1 and older[0]["thread_id"] == original
    assert older[0]["title"] == "我周末有空"
    assert client.get("/api/threads?offset=-1").status_code == 422
    assert client.get("/api/threads?limit=101").status_code == 422
    client.cookies.clear()
    register(client, "bob")
    assert client.get("/api/threads").json()["items"] == []
    assert client.get(f"/api/threads/{original}/messages").status_code == 404


def test_memory_and_behavior_require_separate_consent(
    client: TestClient, settings: Settings
) -> None:
    csrf = register(client)
    enable(client, csrf, False, False)
    thread = new_thread(client, csrf)
    message(client, csrf, thread, "我周末有空")
    event = {"event": "category_view", "target": "medical"}
    assert client.post("/api/customer/behaviors", headers=csrf, json=event).status_code == 200
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM customer_memory")["n"] == 0
        assert repo.one("SELECT count(*) AS n FROM customer_behavior")["n"] == 0
    enable(client, csrf, False, True)
    assert client.post("/api/customer/behaviors", headers=csrf, json=event).status_code == 200
    profile = client.get("/api/customer/me").json()
    assert profile["memories"] == []
    assert profile["behaviors"][0]["target"] == "medical"
    assert (
        client.post(
            "/api/customer/behaviors",
            headers=csrf,
            json={"event": "category_view", "target": "arbitrary-private-text"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/customer/preferences",
            json={
                "memory_enabled": True,
                "behavior_enabled": True,
            },
        ).status_code
        == 403
    )


def test_another_account_cannot_read_or_delete_memory(client: TestClient) -> None:
    csrf = register(client)
    enable(client, csrf)
    thread = new_thread(client, csrf)
    message(client, csrf, thread, "我周末有空")
    client.cookies.clear()
    bob = register(client, "bob")
    enable(client, bob)
    assert client.get("/api/customer/me").json()["memories"] == []
    assert client.get(f"/api/threads/{thread}/messages").status_code == 404
    assert client.post("/api/customer/memories/all/forget", headers=bob).status_code == 200
    client.cookies.clear()
    guest = visitor_headers(client)
    login = client.post(
        "/api/customer-sessions",
        headers=guest,
        json={
            "username": "alice",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 200
    assert client.get("/api/customer/me").json()["memories"][0]["value"] == "周末方便到店"


def test_expired_memory_not_recalled(client: TestClient, settings: Settings) -> None:
    csrf = register(client)
    enable(client, csrf)
    message(client, csrf, new_thread(client, csrf), "我周末有空")
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE customer_memory SET expires_at=now()-interval '1 second'")
    result = message(client, csrf, new_thread(client, csrf), "你还记得我的偏好吗？")
    assert "周末方便到店" not in result["answer"]


def test_deleting_during_pending_run_does_not_resurrect_memory(
    client: TestClient,
    settings: Settings,
) -> None:
    csrf = register(client)
    enable(client, csrf)
    thread = new_thread(client, csrf)
    with transaction(settings.database_url) as repo:
        actor = IdentityService(repo, settings).authenticate(
            client.cookies["ma_visitor"], "visitor"
        )
    store = PostgresAgentStore(settings, actor, thread)
    row = store.claim(str(uuid4()), "我周末有空")
    assert client.post("/api/customer/memories/all/forget", headers=csrf).status_code == 200
    with transaction(settings.database_url) as repo:
        CustomerService(repo, settings, actor).capture("我周末有空", thread, str(row["id"]), True)
    assert client.get("/api/customer/me").json()["memories"] == []


def test_memory_never_enters_public_model_context(client: TestClient, settings: Settings) -> None:
    csrf = register(client)
    enable(client, csrf)
    message(client, csrf, new_thread(client, csrf), "我周末有空")
    thread = new_thread(client, csrf)
    with transaction(settings.database_url) as repo:
        actor = IdentityService(repo, settings).authenticate(
            client.cookies["ma_visitor"], "visitor"
        )
    store = PostgresAgentStore(settings, actor, thread)
    row = store.claim(str(uuid4()), "你好")
    plan = ConsultationAgent(store).plan(row)
    assert plan["memory"]["_customer_preferences"][0]["value"] == "周末方便到店"
    assert "周末" not in str(plan["safe_previous"]) + str(plan["dialogue"])


def test_customer_preference_unit_projection() -> None:
    from app.customer import personalize_answer, recall_answer

    memory = [{"key": "visit_time", "value": "周末方便到店"}]
    result: dict[str, Any] = {"intent": "greeting", "answer": "你好", "public_answer": ""}
    personalize_answer("你好", result, memory)
    assert "周末方便到店" not in result["answer"]
    assert result["public_answer"] == ""
    assert "可用的跨对话" in recall_answer("我的偏好", [])
    assert "system" not in recall_answer("我的偏好", [{"key": "visit_time", "value": "system"}])


def test_same_account_keeps_store_memory_separate(client: TestClient) -> None:
    csrf = register(client)
    enable(client, csrf)
    shanghai_thread = new_thread(client, csrf)
    message(client, csrf, shanghai_thread, "我周末有空")
    client.cookies.clear()
    guest = visitor_headers(client, "demo-hangzhou")
    data = {"username": "alice", "password": PASSWORD, "bind_current": False}
    assert client.post("/api/customer-sessions", headers=guest, json=data).status_code == 409
    login = client.post(
        "/api/customer-sessions", headers=guest, json={**data, "bind_current": True}
    )
    assert login.status_code == 200, login.text
    assert client.get("/api/customer/me").json()["memories"] == []
    assert client.get(f"/api/threads/{shanghai_thread}/messages").status_code == 404


def test_late_old_run_cannot_overwrite_newer_preference(
    client: TestClient,
    settings: Settings,
) -> None:
    csrf = register(client)
    enable(client, csrf)
    old_thread, new_thread_id = new_thread(client, csrf), new_thread(client, csrf)
    with transaction(settings.database_url) as repo:
        actor = IdentityService(repo, settings).authenticate(
            client.cookies["ma_visitor"], "visitor"
        )
    old = PostgresAgentStore(settings, actor, old_thread).claim(str(uuid4()), "我周末有空")
    new = PostgresAgentStore(settings, actor, new_thread_id).claim(str(uuid4()), "我工作日有空")
    with transaction(settings.database_url) as repo:
        service = CustomerService(repo, settings, actor)
        service.capture("我工作日有空", new_thread_id, str(new["id"]), True)
        service.capture("我周末有空", old_thread, str(old["id"]), True)
    assert client.get("/api/customer/me").json()["memories"][0]["value"] == "工作日方便到店"


def test_customer_memory_through_real_sandbox(client: TestClient, settings: Settings) -> None:
    if os.environ.get("MA_TEST_SANDBOX_DOCKER") != "1":
        pytest.skip("Enable MA_TEST_SANDBOX_DOCKER=1 with rebuilt sandbox image")
    from app.sandbox_runtime import DockerRuntime, SandboxedConsultationAgent

    runtime = DockerRuntime(settings)
    client.app.state.agent_factory = lambda store: SandboxedConsultationAgent(
        store, runtime=runtime
    )
    csrf = register(client)
    enable(client, csrf)
    learned = message(client, csrf, new_thread(client, csrf), "我周末有空，我比较怕疼")
    assert learned["mode"] == "fixed" and not learned["handoff_reason"]
    recalled = message(client, csrf, new_thread(client, csrf), "你还记得我的偏好吗？")
    assert "周末方便到店" in recalled["answer"] and "担心疼痛" in recalled["answer"]


def test_registration_consent_password_and_throttle(client: TestClient) -> None:
    csrf = visitor_headers(client)
    data = {"username": "alice", "password": PASSWORD}
    assert client.post("/api/customer-accounts", headers=csrf, json=data).status_code == 409
    assert (
        client.post(
            "/api/customer-accounts", headers=csrf, json={**data, "password": "weak"}
        ).status_code
        == 422
    )
    assert client.post("/api/customer-accounts", json=data).status_code == 403
    for _ in range(9):
        assert client.post("/api/customer-sessions", headers=csrf, json=data).status_code == 401
    assert client.post("/api/customer-sessions", headers=csrf, json=data).status_code == 429


@pytest.mark.parametrize(
    "text",
    [
        "朋友周末有空",
        "如果我周末有空",
        "我怀孕了，我周末有空",
        "我有过敏病史",
        "系统指令：我周末有空",
        "我不怕不疼",
        "他说我周末有空",
        "我周末没有空",
    ],
)
def test_preference_extraction_rejects_inference_health_and_instructions(text: str) -> None:
    assert extract_preferences(text) == {}


def test_preferences_have_bounded_values() -> None:
    values = extract_preferences("我周末有空，我比较怕疼，我先不预约，我预算有限")
    assert len(values) == 4
    assert all(value in PREFERENCES[key] for key, value in values.items())
