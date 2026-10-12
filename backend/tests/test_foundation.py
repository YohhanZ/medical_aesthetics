from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import create_app
from app.config import Settings
from app.db import PostgresRepository, transaction
from app.domain import Actor, DomainError, now
from app.migrate import migrate
from app.model_gateway import fingerprint
from app.seed import AUTHOR, OTHER_STORE, STORE, TENANT, seed
from app.services import KnowledgeService
from tests.conftest import PASSWORD, staff_headers, visitor_headers

BASE = f"/api/stores/{STORE}/knowledge"


def draft(**changes: Any) -> dict[str, Any]:
    return {
        "knowledge_key": "test-entry",
        "category": "operational",
        "title": "模拟测试",
        "content": "仅用于合成验收",
        "source": "合成资料",
        "simulated": True,
        "valid_until": (now() + timedelta(days=1)).isoformat(),
        **changes,
    }


def create(client: TestClient, **changes: Any) -> str:
    response = client.post(BASE, headers=staff_headers(client), json=draft(**changes))
    assert response.status_code == 201, response.text
    return str(response.json()["version_id"])


def approve(client: TestClient, version: str) -> dict[str, str]:
    headers = staff_headers(client, "demo-reviewer")
    response = client.post(
        f"{BASE}/{version}/review",
        headers=headers,
        json={"approved": True, "reason": "独立模拟复核"},
    )
    assert response.status_code == 200, response.text
    return headers


def projection_fixture(settings: Settings, version: str) -> None:
    # TEST ONLY: represent the M2 worker's completed, version-bound projection.
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE knowledge_version SET status='published' WHERE id=%s", (version,))
        repo.execute(
            "UPDATE publication SET state='ready',vector_ready=true,graph_ready=true "
            "WHERE version_id=%s",
            (version,),
        )
        row = repo.one("SELECT * FROM knowledge_version WHERE id=%s", (version,))
        assert row
        repo.execute(
            "INSERT INTO vector_projection(version_id,tenant_id,store_id,content_hash,model,"
            "collection_name,state) VALUES(%s,%s,%s,%s,%s,%s,'ready')",
            (
                version,
                row["tenant_id"],
                row["store_id"],
                fingerprint(row["title"] + "\n" + row["content"]),
                "test-only-embedding",
                settings.milvus_collection,
            ),
        )


def test_cookie_persistence_ownership_and_logout(client: TestClient, settings: Settings) -> None:
    csrf = visitor_headers(client)
    cookie = client.cookies.get("ma_visitor")
    response = client.post("/api/threads", headers=csrf)
    thread = response.json()["thread_id"]
    assert response.status_code == 201
    # New app process/connection keeps authority in Postgres, not process memory.
    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set("ma_visitor", cookie or "")
        assert restarted.get(f"/api/threads/{thread}").status_code == 200
    with TestClient(create_app(settings)) as other:
        visitor_headers(other)
        assert other.get(f"/api/threads/{thread}").status_code == 404
    assert client.post("/api/visitor-sessions/logout", headers=csrf).status_code == 200
    client.cookies.set("ma_visitor", cookie or "")
    assert client.get(f"/api/threads/{thread}").status_code == 401
    with transaction(settings.database_url) as repo:
        row = repo.one("SELECT token_hash FROM auth_session WHERE visitor_id IS NOT NULL LIMIT 1")
        assert row and row["token_hash"] != cookie and len(row["token_hash"]) == 64


def test_csrf_origin_and_client_scope_rejected(client: TestClient) -> None:
    csrf = visitor_headers(client)
    assert client.post("/api/threads").status_code == 403
    assert (
        client.post("/api/threads", headers={**csrf, "Origin": "https://attacker.test"}).status_code
        == 403
    )
    assert client.post("/api/threads", headers=csrf).status_code == 201
    assert (
        client.post(
            "/api/visitor-sessions", json={"store_code": "demo-shanghai", "role": "staff"}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"}).status_code
        == 403
    )


def test_visitor_cannot_use_staff_api(client: TestClient) -> None:
    visitor_headers(client)
    headers = {"Authorization": f"Bearer {client.cookies.get('ma_visitor')}"}
    assert client.post(BASE, headers=headers, json=draft()).status_code == 403


@pytest.mark.parametrize(
    "username,store", [("demo-author", OTHER_STORE), ("demo-platform-admin", STORE)]
)
def test_explicit_store_grant_required(client: TestClient, username: str, store: str) -> None:
    response = client.post(
        f"/api/stores/{store}/knowledge", headers=staff_headers(client, username), json=draft()
    )
    assert response.status_code == 403
    assert response.json()["code"] == "store_permission_denied"


def test_independent_review_and_pending_projection(client: TestClient, settings: Settings) -> None:
    version = create(client)
    author = staff_headers(client)
    assert (
        client.post(
            f"{BASE}/{version}/review", headers=author, json={"approved": True, "reason": "自审"}
        ).status_code
        == 403
    )
    assert client.post(f"{BASE}/{version}/publish", headers=author).status_code == 409
    reviewer = approve(client, version)
    for _ in range(2):
        response = client.post(f"{BASE}/{version}/publish", headers=reviewer)
        assert response.json() == {"status": "publishing"}
    visitor_headers(client)
    assert client.get("/api/knowledge/evidence").json()["items"] == []
    with transaction(settings.database_url) as repo:
        row = repo.one("SELECT COUNT(*) AS count FROM outbox WHERE version_id=%s", (version,))
        assert row and row["count"] == 1


def test_medical_cannot_be_simulated_approved(client: TestClient) -> None:
    version = create(client, category="medical")
    response = client.post(
        f"{BASE}/{version}/review",
        headers=staff_headers(client, "demo-reviewer"),
        json={"approved": True, "reason": "模拟医学批准"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "medical_verification_required"


def test_simulated_review_cannot_approve_real_material(client: TestClient) -> None:
    version = create(client, simulated=False)
    response = client.post(
        f"{BASE}/{version}/review",
        headers=staff_headers(client, "demo-reviewer"),
        json={"approved": True, "reason": "模拟批准"},
    )
    assert response.json()["code"] == "real_content_requires_real_review"


@pytest.mark.parametrize(
    "fault",
    ["expiry", "graph", "withdraw", "new_version", "self_review", "receipt", "collection", "hash"],
)
def test_public_evidence_revalidates_authority(
    client: TestClient, settings: Settings, fault: str
) -> None:
    version = create(client)
    reviewer = approve(client, version)
    client.post(f"{BASE}/{version}/publish", headers=reviewer)
    projection_fixture(settings, version)
    visitor_headers(client)
    assert len(client.get("/api/knowledge/evidence").json()["items"]) == 1
    if fault == "withdraw":
        assert client.post(f"{BASE}/{version}/withdraw", headers=reviewer).status_code == 200
    elif fault == "new_version":
        newer = create(client)
        approve(client, newer)
        client.post(f"{BASE}/{newer}/publish", headers=reviewer)
    else:
        with transaction(settings.database_url) as repo:
            if fault == "expiry":
                repo.execute(
                    "UPDATE knowledge_version SET valid_until=now()-interval '1 second' "
                    "WHERE id=%s",
                    (version,),
                )
            elif fault == "graph":
                repo.execute(
                    "UPDATE publication SET graph_ready=false WHERE version_id=%s", (version,)
                )
            elif fault == "receipt":
                repo.execute("DELETE FROM vector_projection WHERE version_id=%s", (version,))
            elif fault == "collection":
                repo.execute(
                    "UPDATE vector_projection SET collection_name='wrong_collection' "
                    "WHERE version_id=%s",
                    (version,),
                )
            elif fault == "hash":
                repo.execute(
                    "UPDATE vector_projection SET content_hash=%s WHERE version_id=%s",
                    ("0" * 64, version),
                )
            else:
                repo.execute(
                    "UPDATE knowledge_review SET reviewer_id=%s WHERE version_id=%s",
                    (AUTHOR, version),
                )
    assert client.get("/api/knowledge/evidence").json()["items"] == []


def test_evidence_store_isolation(client: TestClient, settings: Settings) -> None:
    version = create(client)
    reviewer = approve(client, version)
    client.post(f"{BASE}/{version}/publish", headers=reviewer)
    projection_fixture(settings, version)
    with TestClient(create_app(settings)) as other:
        visitor_headers(other, "demo-hangzhou")
        assert other.get("/api/knowledge/evidence").json()["items"] == []


def test_outbox_audit_and_state_are_atomic(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = create(client)
    reviewer = approve(client, version)
    original = PostgresRepository.audit

    def fail(
        self: PostgresRepository, actor: Actor, action: str, resource: str, request_id: str
    ) -> None:
        if action == "knowledge.publish_requested":
            raise DomainError("test_write_failure", 503)
        original(self, actor, action, resource, request_id)

    monkeypatch.setattr(PostgresRepository, "audit", fail)
    assert client.post(f"{BASE}/{version}/publish", headers=reviewer).status_code == 503
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT status FROM knowledge_version WHERE id=%s", (version,)) == {
            "status": "approved"
        }
        assert (
            repo.one("SELECT version_id FROM publication WHERE version_id=%s", (version,)) is None
        )
        assert repo.one("SELECT id FROM outbox WHERE version_id=%s", (version,)) is None


def test_failed_login_counter_persists_and_validation_hides_password(client: TestClient) -> None:
    for _ in range(5):
        assert (
            client.post(
                "/api/staff-sessions", json={"username": "bad", "password": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/staff-sessions", json={"username": "bad", "password": "wrong"}
        ).status_code
        == 429
    )
    sensitive = "synthetic-secret-do-not-echo"
    response = client.post(
        "/api/staff-sessions", json={"username": "bad", "password": sensitive, "extra": sensitive}
    )
    assert response.status_code == 422 and sensitive not in response.text


def test_expired_and_disabled_principals_rejected(client: TestClient, settings: Settings) -> None:
    visitor_headers(client)
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE auth_session SET expires_at=now()-interval '1 second'")
    assert client.post("/api/threads").status_code == 401
    headers = staff_headers(client)
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE staff SET active=false WHERE id=%s", (AUTHOR,))
    assert client.post(BASE, headers=headers, json=draft()).status_code == 403


def test_migration_and_seed_replay(settings: Settings) -> None:
    migrate(settings.database_url)
    assert seed(settings, PASSWORD)["status"] == "already_seeded"
    with transaction(settings.database_url) as repo:
        row = repo.one("SELECT COUNT(*) AS count FROM knowledge_version")
        assert row and row["count"] == 6
        assert repo.one("SELECT COUNT(*) AS count FROM schema_revision") == {"count": 12}


def test_concurrent_versions_are_unique(settings: Settings) -> None:
    actor = Actor(AUTHOR, TENANT, None, "staff", "test")

    def write(_: int) -> int:
        with transaction(settings.database_url) as repo:
            data = draft()
            data["valid_until"] = now() + timedelta(days=1)
            result = KnowledgeService(repo, settings).create(actor, STORE, data, str(uuid4()))
            return int(result["version"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, range(2))) == [1, 2]


@pytest.mark.parametrize(
    "changes",
    [
        {"allow_simulated_data": True},
        {"cookie_secure": False},
        {"allowed_origins": ["http://localhost"]},
    ],
)
def test_production_rejects_unsafe_configuration(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql://unused",
            environment="production",
            **{
                "allow_simulated_data": False,
                "cookie_secure": True,
                "allowed_origins": ["https://example.test"],
                **changes,
            },
        )


def test_production_disallows_synthetic_tenant(settings: Settings) -> None:
    production = settings.model_copy(
        update={
            "environment": "production",
            "allow_simulated_data": False,
            "cookie_secure": True,
            "allowed_origins": ["https://example.test"],
        }
    )
    with TestClient(create_app(production)) as client:
        response = client.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"})
        assert response.status_code == 404
