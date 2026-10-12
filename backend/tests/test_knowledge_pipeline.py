"""Real isolated PostgreSQL; explicit in-test adapters never installed in the application."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.db import transaction
from app.domain import Actor, DomainError, now
from app.graph_adapter import Neo4jKnowledgeGraph
from app.knowledge_import import import_dataset
from app.knowledge_types import KnowledgeDetails
from app.knowledge_worker import ProjectionWorker, eligible
from app.model_gateway import GatewayError, fingerprint
from app.retrieval import PostgresEvidenceReader, RetrievalService
from app.seed import AUTHOR, REVIEWER, STORE, TENANT
from app.services import IdentityService, KnowledgeService
from app.vector_adapter import VectorDocument
from tests.conftest import visitor_headers

DATASET = Path(__file__).parents[1] / "data" / "consultation_catalog.json"


class TestEmbedding:
    __test__ = False
    model: str = "test-only-embedding"

    def embed(self, text: str) -> list[float]:
        return [1.0] + [0.0] * 255


class TestVectors:
    __test__ = False
    collection: str = "ma_mock_test_256"

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.upserts = 0

    def inspect(self, document: VectorDocument) -> Literal["missing", "match", "conflict"]:
        existing = self.rows.get(document.id)
        if not existing:
            return "missing"
        expected = document.row([1.0] + [0.0] * 255)
        return (
            "match"
            if all(existing[key] == value for key, value in expected.items() if key != "embedding")
            else "conflict"
        )

    def upsert(self, document: VectorDocument, embedding: list[float]) -> None:
        self.rows[document.id] = document.row(embedding)
        self.upserts += 1

    def remove(self, tenant_id: str, store_id: str, version_id: str) -> None:
        row = self.rows.get(version_id)
        if row and (row["tenant_id"], row["store_id"]) == (tenant_id, store_id):
            self.rows.pop(version_id)

    def search(
        self,
        tenant_id: str,
        store_id: str,
        version_ids: list[str],
        embedding: list[float],
        model: str,
        allow_simulated: bool,
    ) -> list[dict[str, Any]]:
        return [
            {
                "version_id": row["id"],
                "content_hash": row["content_hash"],
                "model": row["model"],
                "version": row["version"],
                "score": 1.0,
            }
            for row in self.rows.values()
            if row["id"] in version_ids
            and row["tenant_id"] == tenant_id
            and row["store_id"] == store_id
            and row["model"] == model
            and row["audience"] == "public"
            and row["valid_until"] > now().timestamp()
            and (allow_simulated or not row["simulated"])
        ]


class TestGraph:
    __test__ = False

    def __init__(self) -> None:
        self.vectors = TestVectors()
        self.versions: dict[str, dict[str, Any]] = {}
        self.fail = False
        self.on_expand: Callable[[], None] = lambda: None

    def project(self, version: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("SENSITIVE-provider-error-do-not-persist")
        self.versions[str(version["id"])] = version

    def remove(self, tenant_id: str, store_id: str, version_id: str) -> None:
        self.versions.pop(version_id, None)

    def expand(
        self, tenant_id: str, store_id: str, version_ids: list[str], topics: list[str]
    ) -> list[str]:
        self.on_expand()
        if self.fail:
            raise RuntimeError("unavailable")
        return [
            key
            for key in version_ids
            if key in self.versions
            and any(topic in topics for topic in self.versions[key]["topics"])
        ]


def drain(settings: Settings, graph: TestGraph) -> None:
    worker = ProjectionWorker(settings, graph, TestEmbedding(), graph.vectors)
    for _ in range(100):
        result = worker.run_once()
        if result["status"] == "idle":
            return
        assert result["status"] in ("published", "removed"), result
    raise AssertionError("Outbox did not drain")


def visitor_actor(client: TestClient, settings: Settings) -> Actor:
    visitor_headers(client)
    with transaction(settings.database_url) as repo:
        return IdentityService(repo, settings).authenticate(
            client.cookies.get("ma_visitor") or "", "visitor"
        )


def make_newer(settings: Settings, key: str) -> str:
    with transaction(settings.database_url) as repo:
        service = KnowledgeService(repo, settings)
        original = repo.one("SELECT * FROM knowledge_version WHERE knowledge_key=%s", (key,))
        assert original
        data = {
            name: original[name]
            for name in (
                "knowledge_key",
                "category",
                "title",
                "content",
                "source",
                "simulated",
                "valid_until",
            )
        }
        author = Actor(AUTHOR, TENANT, None, "staff", "test")
        reviewer = Actor(REVIEWER, TENANT, None, "staff", "test")
        version = service.create(author, STORE, data, str(uuid4()))["version_id"]
        service.review(reviewer, STORE, version, True, "独立模拟复核", str(uuid4()))
        service.publish(reviewer, STORE, version, str(uuid4()))
        return str(version)


def test_import_idempotency_and_medical_gate(settings: Settings) -> None:
    assert import_dataset(settings, DATASET) == {
        "created": 32,
        "skipped": 0,
        "medical_pending": 4,
        "simulated": True,
    }
    assert import_dataset(settings, DATASET)["skipped"] == 32
    graph = TestGraph()
    drain(settings, graph)
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM knowledge_version") == {"n": 38}
        assert repo.one(
            "SELECT count(*) AS n FROM knowledge_version "
            "WHERE category='medical' AND status='draft'"
        ) == {"n": 5}
        assert repo.one("SELECT count(*) AS n FROM vector_projection WHERE state='ready'") == {
            "n": 33
        }
        assert repo.one("SELECT count(*) AS n FROM knowledge_embedding") == {"n": 0}
        assert repo.one("SELECT count(*) AS n FROM outbox WHERE processed_at IS NULL") == {"n": 0}
        assert all(row["category"] != "medical" for row in graph.versions.values())


def test_import_content_change_creates_version_and_withdrawal_not_resurrected(
    settings: Settings,
    tmp_path: Path,
) -> None:
    original = json.loads(DATASET.read_text("utf-8"))[:1]
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(original), "utf-8")
    import_dataset(settings, path)
    with transaction(settings.database_url) as repo:
        row = repo.one(
            "SELECT id FROM knowledge_version WHERE knowledge_key=%s",
            (original[0]["knowledge_key"],),
        )
        assert row
        KnowledgeService(repo, settings).withdraw(
            Actor(REVIEWER, TENANT, None, "staff", "test"), STORE, str(row["id"]), str(uuid4())
        )
    assert import_dataset(settings, path)["skipped"] == 1
    original[0]["content"] += " 修改后的合成版本。"
    path.write_text(json.dumps(original), "utf-8")
    assert import_dataset(settings, path)["created"] == 1
    with transaction(settings.database_url) as repo:
        rows = repo.all(
            "SELECT version,status FROM knowledge_version WHERE knowledge_key=%s ORDER BY version",
            (original[0]["knowledge_key"],),
        )
        assert rows == [
            {"version": 1, "status": "withdrawn"},
            {"version": 2, "status": "publishing"},
        ]


def test_import_rejects_production_and_invalid_graph_atomically(
    settings: Settings, tmp_path: Path
) -> None:
    with pytest.raises(RuntimeError):
        import_dataset(settings.model_copy(update={"environment": "production"}), DATASET)
    items = json.loads(DATASET.read_text("utf-8"))[:2]
    items[1]["details"]["relations"][0]["target"] = "untrusted-missing-node"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(items), "utf-8")
    with pytest.raises(ValidationError):
        import_dataset(settings, path)
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM knowledge_import") == {"n": 0}


def test_projection_failure_is_sanitized_and_recovers(settings: Settings) -> None:
    graph = TestGraph()
    graph.fail = True
    worker = ProjectionWorker(settings, graph, TestEmbedding(), graph.vectors)
    result = worker.run_once()
    assert result["code"] == "projection_unavailable"
    with transaction(settings.database_url) as repo:
        row = repo.one("SELECT * FROM outbox WHERE id=%s", (result["event_id"],))
        assert row and row["last_error"] == "projection_unavailable" and row["processed_at"] is None
        repo.execute("UPDATE outbox SET available_at=now() WHERE id=%s", (result["event_id"],))
        assert repo.one("SELECT count(*) AS n FROM publication WHERE state='ready'") == {"n": 0}
    graph.fail = False
    assert worker.run_once()["status"] == "published"
    drain(settings, graph)


def test_graph_success_without_embedding_not_published(settings: Settings) -> None:
    class Unavailable(TestEmbedding):
        def embed(self, text: str) -> list[float]:
            raise GatewayError("model_not_configured")

    graph = TestGraph()
    result = ProjectionWorker(settings, graph, Unavailable(), graph.vectors).run_once()
    assert result["code"] == "model_not_configured"
    with transaction(settings.database_url) as repo:
        row = repo.one(
            "SELECT p.* FROM publication p JOIN outbox o "
            "ON o.version_id=p.version_id WHERE o.id=%s",
            (result["event_id"],),
        )
        assert row and row["graph_ready"] and not row["vector_ready"] and row["state"] == "pending"


def test_old_publish_event_does_not_overwrite_newer(settings: Settings) -> None:
    new = make_newer(settings, "consultation-process")
    graph = TestGraph()
    drain(settings, graph)
    assert new in graph.versions
    assert (
        sum(row["knowledge_key"] == "consultation-process" for row in graph.versions.values()) == 1
    )


def test_withdraw_during_external_projection_revalidates(settings: Settings) -> None:
    class WithdrawGraph(TestGraph):
        def project(self, version: dict[str, Any]) -> None:
            super().project(version)
            with transaction(settings.database_url) as repo:
                KnowledgeService(repo, settings).withdraw(
                    Actor(REVIEWER, TENANT, None, "staff", "test"),
                    STORE,
                    str(version["id"]),
                    str(uuid4()),
                )

    graph = WithdrawGraph()
    result = ProjectionWorker(settings, graph, TestEmbedding(), graph.vectors).run_once()
    assert result["code"] == "knowledge_changed"
    target = next(iter(graph.versions))
    assert target not in graph.vectors.rows
    # Other older ready events may run first; fairness must not assume ID-only ordering.
    worker = ProjectionWorker(settings, graph, TestEmbedding(), graph.vectors)
    for _ in range(12):
        result = worker.run_once()
        assert result["status"] in ("retry", "removed")
        if target not in graph.versions:
            assert result["status"] == "removed"
            break
    else:
        raise AssertionError("Withdrawal projection was not removed")
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT status FROM knowledge_version WHERE id=%s", (target,)) == {
            "status": "withdrawn"
        }


def test_active_lease_skipped_and_expired_lease_recovers(settings: Settings) -> None:
    with transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE outbox SET lease_token=%s,lease_until=now()+interval '1 minute'",
            (str(uuid4()),),
        )
    worker = ProjectionWorker(settings, TestGraph(), TestEmbedding(), TestVectors())
    assert worker.run_once()["status"] == "idle"
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE outbox SET lease_until=now()-interval '1 second'")
    assert worker.run_once()["status"] == "published"


def test_retrieval_excludes_internal_and_rechecks_authority(
    client: TestClient, settings: Settings
) -> None:
    import_dataset(settings, DATASET)
    graph = TestGraph()
    drain(settings, graph)
    actor = visitor_actor(client, settings)
    reader = PostgresEvidenceReader(settings)
    result = RetrievalService(reader, graph, TestEmbedding(), graph.vectors, True).search(
        actor, "第一次到店要先确定项目吗"
    )
    assert result["items"] and result["method"] == "hybrid"
    assert len(reader.evidence(actor)) == 25  # 22 new + 3 original public operational entries
    assert all(not str(item["knowledge_key"]).startswith("strategy-") for item in result["items"])

    def withdraw_all() -> None:
        with transaction(settings.database_url) as repo:
            repo.execute(
                "UPDATE knowledge_version SET status='withdrawn' WHERE category='operational'"
            )

    graph.on_expand = withdraw_all
    assert (
        RetrievalService(reader, graph, TestEmbedding(), graph.vectors, True).search(actor, "预约")[
            "items"
        ]
        == []
    )


def test_retrieval_logout_during_adapter_denies(client: TestClient, settings: Settings) -> None:
    graph = TestGraph()
    drain(settings, graph)
    actor = visitor_actor(client, settings)

    def revoke() -> None:
        with transaction(settings.database_url) as repo:
            IdentityService(repo, settings).revoke(actor)

    graph.on_expand = revoke
    with pytest.raises(DomainError) as failure:
        RetrievalService(
            PostgresEvidenceReader(settings), graph, TestEmbedding(), graph.vectors, True
        ).search(actor, "预约")
    assert failure.value.status == 401


def test_empty_search_api_requires_csrf(client: TestClient) -> None:
    csrf = visitor_headers(client)
    assert client.post("/api/knowledge/search", json={"question": "你好"}).status_code == 403
    assert (
        client.post("/api/knowledge/search", headers=csrf, json={"question": "你好"}).json()[
            "method"
        ]
        == "none"
    )


def test_actual_neo4j_projection_idempotency_scope_and_removal(settings: Settings) -> None:
    # Uses the new isolated local Neo4j, unique immutable version IDs; no graph-wide resets.
    graph = Neo4jKnowledgeGraph(settings)
    graph.setup()
    version_id = ""
    try:
        import_dataset(settings, DATASET)
        with transaction(settings.database_url) as repo:
            row = repo.one(
                "SELECT id FROM knowledge_version WHERE knowledge_key='catalog-hydration'"
            )
            assert row
            version_id = str(row["id"])
            version = eligible(repo, version_id, True)
            assert version
            version["content_hash"] = fingerprint(version["title"] + "\n" + version["content"])
        graph.project(version)
        graph.project(version)
        assert graph.expand(TENANT, STORE, [version_id], ["基础补水"]) == [version_id]
        assert graph.expand(str(uuid4()), STORE, [version_id], ["基础补水"]) == []
        records, _, _ = graph.driver.execute_query(
            "MATCH (a:KnowledgeEntity {version_id:$id})-[r:ASSERTION]->() RETURN count(r) AS n",
            id=version_id,
            database_=graph.database,
        )
        assert records[0]["n"] == 1
        graph.remove(TENANT, STORE, version_id)
        assert graph.expand(TENANT, STORE, [version_id], ["基础补水"]) == []
    finally:
        if version_id:
            graph.remove(TENANT, STORE, version_id)
        graph.close()


def test_communication_cannot_be_public(client: TestClient) -> None:
    from tests.conftest import staff_headers
    from tests.test_foundation import draft

    result = client.post(
        f"/api/stores/{STORE}/knowledge",
        headers=staff_headers(client),
        json=draft(category="communication", details=KnowledgeDetails().model_dump()),
    )
    assert result.status_code == 422 and result.json()["code"] == "internal_strategy_required"


def test_dataset_disabled_author_cannot_write(settings: Settings) -> None:
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE staff SET active=false WHERE id=%s", (AUTHOR,))
    with pytest.raises(DomainError):
        import_dataset(settings, DATASET)
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM knowledge_import") == {"n": 0}


def test_lease_lost_during_embedding_cannot_mark_published(settings: Settings) -> None:
    class LeaseLost(TestEmbedding):
        def embed(self, text: str) -> list[float]:
            with transaction(settings.database_url) as repo:
                repo.execute("UPDATE outbox SET lease_until=now()-interval '1 second'")
            return super().embed(text)

    assert (
        ProjectionWorker(settings, TestGraph(), LeaseLost(), TestVectors()).run_once()["status"]
        == "lease_lost"
    )
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM publication WHERE state='ready'") == {"n": 0}
        assert repo.one("SELECT count(*) AS n FROM knowledge_embedding") == {"n": 0}


def test_retrieval_can_use_published_lexical_evidence_when_adapters_fail(
    client: TestClient,
    settings: Settings,
) -> None:
    graph = TestGraph()
    drain(settings, graph)
    actor = visitor_actor(client, settings)
    graph.fail = True

    class Unavailable(TestEmbedding):
        def embed(self, text: str) -> list[float]:
            raise GatewayError("model_unavailable")

    result = RetrievalService(
        PostgresEvidenceReader(settings), graph, Unavailable(), graph.vectors, True
    ).search(actor, "到店")
    assert (
        result["items"]
        and result["method"] == "lexical"
        and result["graph_status"] == "unavailable"
    )
