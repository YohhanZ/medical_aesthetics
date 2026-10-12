"""Leased outbox projection. No database transaction is held during external calls."""

import argparse
import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.db import PostgresRepository, transaction
from app.domain import now
from app.graph_adapter import KnowledgeGraph, Neo4jKnowledgeGraph
from app.knowledge_scope import MEDICAL_VISIBILITY_SQL
from app.model_gateway import Embedder, GatewayError, QwenEmbeddingGateway, fingerprint
from app.vector_adapter import MilvusVectorStore, VectorDocument, VectorError, VectorStore


def eligible(
    repo: PostgresRepository, version_id: str, allow_simulated: bool, demo_education: bool = False
) -> dict[str, Any] | None:
    return repo.one(
        "SELECT k.*,d.audience,d.topics,d.entities,d.relations FROM knowledge_version k "
        "JOIN knowledge_detail d ON d.version_id=k.id "
        "JOIN knowledge_review r ON r.version_id=k.id "
        "JOIN publication p ON p.version_id=k.id "
        "JOIN store s ON (s.tenant_id,s.id)=(k.tenant_id,k.store_id) "
        "JOIN tenant t ON t.id=k.tenant_id "
        "WHERE k.id=%s AND k.status IN ('publishing','published') "
        "AND p.state IN ('pending','ready') AND k.valid_until>now() AND s.active "
        "AND " + MEDICAL_VISIBILITY_SQL + "AND r.approved AND r.reviewer_id<>k.author_id "
        "AND (%s OR NOT(k.simulated OR r.simulated OR s.simulated OR t.simulated)) "
        "AND NOT EXISTS(SELECT 1 FROM knowledge_version n WHERE n.tenant_id=k.tenant_id "
        "AND n.store_id=k.store_id AND n.knowledge_key=k.knowledge_key AND n.version>k.version "
        "AND n.status IN ('publishing','published','withdrawn'))",
        (version_id, demo_education and allow_simulated, allow_simulated),
    )


def embedding_text(version: dict[str, Any]) -> str:
    return str(version["title"]) + "\n" + str(version["content"])


class ProjectionWorker:
    def __init__(
        self, settings: Settings, graph: KnowledgeGraph, embedder: Embedder, vectors: VectorStore
    ) -> None:
        self.settings, self.graph, self.embedder = settings, graph, embedder
        self.vectors = vectors

    def run_once(self) -> dict[str, Any]:
        lease = str(uuid4())
        with transaction(self.settings.database_url) as repo:
            event = repo.one(
                "WITH next AS (SELECT id FROM outbox WHERE processed_at IS NULL "
                "AND available_at<=now() AND (lease_until IS NULL OR lease_until<now()) "
                "ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT 1) "
                "UPDATE outbox o SET lease_token=%s,lease_until=now()+interval '90 seconds',"
                "attempts=attempts+1 FROM next WHERE o.id=next.id RETURNING o.*",
                (lease,),
            )
            if not event:
                return {"status": "idle"}
            version_id = str(event["version_id"])
            version = eligible(
                repo,
                version_id,
                self.settings.allow_simulated_data,
                self.settings.demo_medical_enabled,
            )
        try:
            if event["topic"] == "withdraw" or version is None:
                self.graph.remove(str(event["tenant_id"]), str(event["store_id"]), version_id)
                self.vectors.remove(str(event["tenant_id"]), str(event["store_id"]), version_id)
                with transaction(self.settings.database_url) as repo:
                    if not self._owns(repo, event, lease):
                        return {"status": "lease_lost"}
                    repo.execute(
                        "UPDATE vector_projection SET state='removed',updated_at=now() "
                        "WHERE version_id=%s",
                        (version_id,),
                    )
                    repo.execute(
                        "UPDATE publication SET graph_ready=false,vector_ready=false "
                        "WHERE version_id=%s",
                        (version_id,),
                    )
                    self._complete(repo, event, lease)
                return {"status": "removed", "event_id": event["id"]}
            text = embedding_text(version)
            version["content_hash"] = fingerprint(text)
            self.graph.project(version)
            with transaction(self.settings.database_url) as repo:
                if not self._owns(repo, event, lease):
                    return {"status": "lease_lost"}
                current = eligible(
                    repo,
                    version_id,
                    self.settings.allow_simulated_data,
                    self.settings.demo_medical_enabled,
                )
                if current is None:
                    self._retry(repo, event, lease, "knowledge_changed", immediate=True)
                    return {"status": "retry", "code": "knowledge_changed"}
                repo.execute(
                    "UPDATE publication SET graph_ready=true WHERE version_id=%s", (version_id,)
                )
            document = VectorDocument(
                id=version_id,
                tenant_id=str(version["tenant_id"]),
                store_id=str(version["store_id"]),
                knowledge_key=version["knowledge_key"],
                version=version["version"],
                content_hash=fingerprint(text),
                model=self.embedder.model,
                audience=version["audience"],
                simulated=version["simulated"],
                valid_until=version["valid_until"],
            )
            # Reconcile even when a previous attempt timed out: never blindly repeat an upsert.
            found = self.vectors.inspect(document)
            if found == "conflict":
                raise VectorError("vector_metadata_conflict")
            if found == "missing":
                vector = self.embedder.embed(text)
                with transaction(self.settings.database_url) as repo:
                    if not self._owns(repo, event, lease):
                        return {"status": "lease_lost"}
                    current = eligible(
                        repo,
                        version_id,
                        self.settings.allow_simulated_data,
                        self.settings.demo_medical_enabled,
                    )
                    if current is None or embedding_text(current) != text:
                        self._retry(repo, event, lease, "knowledge_changed", immediate=True)
                        return {"status": "retry", "code": "knowledge_changed"}
                    self._receipt(repo, document, "unknown")
                self.vectors.upsert(document, vector)
                if self.vectors.inspect(document) != "match":
                    raise VectorError("vector_write_unconfirmed")
            with transaction(self.settings.database_url) as repo:
                if not self._owns(repo, event, lease):
                    return {"status": "lease_lost"}
                # Serialize final readiness against concurrent withdrawal/review/version creation.
                repo.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    (f"{version['tenant_id']}/{version['store_id']}/{version['knowledge_key']}",),
                )
                repo.one("SELECT id FROM knowledge_version WHERE id=%s FOR UPDATE", (version_id,))
                current = eligible(
                    repo,
                    version_id,
                    self.settings.allow_simulated_data,
                    self.settings.demo_medical_enabled,
                )
                if current is None or embedding_text(current) != text:
                    self._retry(repo, event, lease, "knowledge_changed", immediate=True)
                    return {"status": "retry", "code": "knowledge_changed"}
                self._receipt(repo, document, "ready")
                repo.execute(
                    "UPDATE publication SET vector_ready=true,state='ready' WHERE version_id=%s",
                    (version_id,),
                )
                repo.execute(
                    "UPDATE knowledge_version SET status='published' WHERE id=%s", (version_id,)
                )
                self._complete(repo, event, lease)
            return {"status": "published", "event_id": event["id"]}
        except Exception as error:
            # No external body/message/credentials enter persisted diagnostics.
            code = (
                error.code
                if isinstance(error, GatewayError | VectorError)
                else "projection_unavailable"
            )
            with transaction(self.settings.database_url) as repo:
                self._retry(repo, event, lease, code)
            return {"status": "retry", "code": code, "event_id": event["id"]}

    def _receipt(self, repo: PostgresRepository, document: VectorDocument, state: str) -> None:
        repo.execute(
            "INSERT INTO vector_projection(version_id,tenant_id,store_id,content_hash,model,"
            "collection_name,state) VALUES(%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(version_id) DO UPDATE SET content_hash=excluded.content_hash,"
            "model=excluded.model,collection_name=excluded.collection_name,state=excluded.state,"
            "updated_at=now()",
            (
                document.id,
                document.tenant_id,
                document.store_id,
                document.content_hash,
                document.model,
                self.vectors.collection,
                state,
            ),
        )

    def _owns(self, repo: PostgresRepository, event: dict[str, Any], lease: str) -> bool:
        return (
            repo.one(
                "SELECT id FROM outbox WHERE id=%s AND lease_token=%s AND lease_until>now() "
                "AND processed_at IS NULL FOR UPDATE",
                (event["id"], lease),
            )
            is not None
        )

    def _complete(self, repo: PostgresRepository, event: dict[str, Any], lease: str) -> None:
        repo.execute(
            "UPDATE outbox SET processed_at=now(),lease_token=NULL,"
            "lease_until=NULL,last_error=NULL "
            "WHERE id=%s AND lease_token=%s",
            (event["id"], lease),
        )

    def _retry(
        self,
        repo: PostgresRepository,
        event: dict[str, Any],
        lease: str,
        code: str,
        immediate: bool = False,
    ) -> None:
        delay = 0 if immediate else min(300, 2 ** min(event["attempts"], 8))
        repo.execute(
            "UPDATE outbox SET lease_token=NULL,lease_until=NULL,last_error=%s,available_at=%s "
            "WHERE id=%s AND lease_token=%s AND lease_until>now() AND processed_at IS NULL",
            (code, now() + timedelta(seconds=delay), event["id"], lease),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-events", type=int, choices=range(1, 1001), default=500, metavar="1..1000"
    )
    args = parser.parse_args()
    settings = Settings()
    graph = Neo4jKnowledgeGraph(settings)
    gateway = QwenEmbeddingGateway(settings)
    vectors = MilvusVectorStore(settings, write=True)
    try:
        graph.setup()
        worker = ProjectionWorker(settings, graph, gateway, vectors)
        for _ in range(args.max_events):
            result = worker.run_once()
            print(json.dumps(result))
            if result["status"] == "idle":
                break
    finally:
        gateway.close()
        graph.close()
        vectors.close()
