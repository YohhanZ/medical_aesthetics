"""External projection reconciliation and expanded corpus checks on the isolated test DB."""

import json
from pathlib import Path
from typing import Literal

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import transaction
from app.knowledge_import import import_dataset
from app.knowledge_worker import ProjectionWorker
from app.model_gateway import GatewayError
from app.retrieval import PostgresEvidenceReader, RetrievalService
from app.vector_adapter import MilvusVectorStore, VectorDocument, VectorError
from tests.test_knowledge_pipeline import TestEmbedding, TestGraph, TestVectors, visitor_actor


def make_available(settings: Settings) -> None:
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE outbox SET available_at=now() WHERE processed_at IS NULL")


def test_unknown_milvus_write_reconciles_without_duplicate_embedding(settings: Settings) -> None:
    class CountingEmbedding(TestEmbedding):
        calls = 0

        def embed(self, text: str) -> list[float]:
            self.calls += 1
            return super().embed(text)

    class CommitThenTimeout(TestVectors):
        def upsert(self, document: VectorDocument, embedding: list[float]) -> None:
            super().upsert(document, embedding)
            raise VectorError("vector_write_unknown")

    vectors, embedding = CommitThenTimeout(), CountingEmbedding()
    worker = ProjectionWorker(settings, TestGraph(), embedding, vectors)
    first = worker.run_once()
    assert first["code"] == "vector_write_unknown"
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT state FROM vector_projection") == {"state": "unknown"}
        assert repo.one("SELECT count(*) AS n FROM publication WHERE state='ready'") == {"n": 0}
    make_available(settings)
    assert worker.run_once()["status"] == "published"
    assert vectors.upserts == 1 and embedding.calls == 1
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT state FROM vector_projection") == {"state": "ready"}


def test_reconciliation_query_failure_never_blindly_repeats_write(settings: Settings) -> None:
    class UnavailableQuery(TestVectors):
        def inspect(self, document: VectorDocument) -> Literal["missing", "match", "conflict"]:
            raise VectorError("vector_query_unavailable")

    vectors = UnavailableQuery()
    worker = ProjectionWorker(settings, TestGraph(), TestEmbedding(), vectors)
    for _ in range(2):
        assert worker.run_once()["code"] == "vector_query_unavailable"
        make_available(settings)
    assert vectors.upserts == 0


def test_conflicting_milvus_metadata_cannot_publish(settings: Settings) -> None:
    class Conflict(TestVectors):
        def inspect(self, document: VectorDocument) -> Literal["missing", "match", "conflict"]:
            return "conflict"

    vectors = Conflict()
    assert (
        ProjectionWorker(settings, TestGraph(), TestEmbedding(), vectors).run_once()["code"]
        == "vector_metadata_conflict"
    )
    assert vectors.upserts == 0


def test_real_worker_and_retrieval_with_isolated_milvus(
    client: TestClient, settings: Settings
) -> None:
    # Fixed test vectors verify the real external pipeline, never Qwen semantic quality.
    config = settings.model_copy(update={"milvus_collection": "ma_knowledge_test_256"})
    assert config.milvus_uri == "http://127.0.0.1:59531"
    writer, reader = MilvusVectorStore(config, write=True), MilvusVectorStore(config)
    graph = TestGraph()
    try:
        assert ProjectionWorker(config, graph, TestEmbedding(), writer).run_once()["status"] == (
            "published"
        )
        actor = visitor_actor(client, config)
        service = RetrievalService(
            PostgresEvidenceReader(config), graph, TestEmbedding(), reader, True
        )
        result = service.search(actor, "首次到店咨询需要准备什么？")
        assert result["method"] == "hybrid" and len(result["items"]) == 1
        with transaction(config.database_url) as repo:
            receipt = repo.one("SELECT state,collection_name FROM vector_projection")
            assert receipt == {"state": "ready", "collection_name": writer.collection}
            assert repo.one("SELECT count(*) AS n FROM knowledge_embedding") == {"n": 0}
    finally:
        for version in graph.versions.values():
            writer.remove(str(version["tenant_id"]), str(version["store_id"]), str(version["id"]))
        reader.close()
        writer.close()


def test_expanded_corpus_structure_import_and_holdout_retrieval(
    client: TestClient,
    settings: Settings,
) -> None:
    data = Path(__file__).parents[1] / "data"
    result = import_dataset(settings, data / "consultation_expanded.json")
    assert result["created"] == 226 and result["medical_pending"] == 20
    assert import_dataset(settings, data / "consultation_expanded.json")["skipped"] == 226
    graph = TestGraph()
    worker = ProjectionWorker(settings, graph, TestEmbedding(), graph.vectors)
    for _ in range(300):
        if worker.run_once()["status"] == "idle":
            break
    else:
        raise AssertionError("Expanded outbox did not drain")

    class Offline(TestEmbedding):
        def embed(self, text: str) -> list[float]:
            raise GatewayError("model_not_configured")

    actor = visitor_actor(client, settings)
    service = RetrievalService(
        PostgresEvidenceReader(settings), graph, Offline(), graph.vectors, True
    )
    cases = json.loads((data / "retrieval_holdout.json").read_text("utf-8"))
    hits = 0
    missed: list[str] = []
    for case in cases:
        items = service.search(actor, case["question"])["items"]
        keys = [item["knowledge_key"] for item in items]
        assert all(not key.startswith(("medical-", "sales-", "dialog-")) for key in keys)
        if case["expected_key"] in keys:
            hits += 1
        else:
            missed.append(case["expected_key"])
    # Measures lexical fallback only; never report synthetic vector tests as semantic model quality.
    assert hits / len(cases) >= 0.8, {"hits": hits, "cases": len(cases), "missed_keys": missed}
    print(f"held-out lexical recall@5: {hits}/{len(cases)}")
    with transaction(settings.database_url) as repo:
        assert repo.one(
            "SELECT count(*) AS n FROM knowledge_version "
            "WHERE category='medical' AND status='draft'"
        ) == {"n": 21}
        assert repo.one("SELECT count(*) AS n FROM knowledge_embedding") == {"n": 0}
