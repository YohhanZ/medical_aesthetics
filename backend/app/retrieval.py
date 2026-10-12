"""Bounded evidence retrieval; PostgreSQL authority is checked before and after adapters."""

import re
from typing import Any, Protocol

from app.config import Settings
from app.db import transaction
from app.domain import Actor, DomainError
from app.graph_adapter import KnowledgeGraph
from app.model_gateway import Embedder, GatewayError, fingerprint
from app.services import KnowledgeService
from app.vector_adapter import VectorError, VectorStore


class EvidenceReader(Protocol):
    def evidence(self, actor: Actor) -> list[dict[str, Any]]: ...
    def details(self, ids: list[str]) -> list[dict[str, Any]]: ...


class PostgresEvidenceReader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evidence(self, actor: Actor) -> list[dict[str, Any]]:
        with transaction(self.settings.database_url) as repo:
            session = repo.one(
                "SELECT a.id FROM auth_session a JOIN store s "
                "ON (s.tenant_id,s.id)=(a.tenant_id,a.store_id) "
                "JOIN tenant t ON t.id=a.tenant_id WHERE a.id=%s AND a.visitor_id=%s "
                "AND a.tenant_id=%s AND a.store_id=%s AND a.revoked_at IS NULL "
                "AND a.expires_at>now() AND s.active AND (%s OR NOT(s.simulated OR t.simulated))",
                (
                    actor.session_id,
                    actor.id,
                    actor.tenant_id,
                    actor.store_id,
                    self.settings.allow_simulated_data,
                ),
            )
            if not session or actor.kind != "visitor":
                raise DomainError("unauthenticated", 401)
            return KnowledgeService(repo, self.settings).evidence(actor)

    def details(self, ids: list[str]) -> list[dict[str, Any]]:
        with transaction(self.settings.database_url) as repo:
            return repo.all(
                "SELECT version_id,topics,entities,guidance FROM knowledge_detail "
                "WHERE version_id=ANY(%s::uuid[])",
                (ids,),
            )


def terms(text: str) -> set[str]:
    result = set(re.findall(r"[a-z0-9]+", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        result.update(run[index : index + 2] for index in range(max(0, len(run) - 1)))
        if len(run) == 1:
            result.add(run)
    return result


class RetrievalService:
    def __init__(
        self,
        reader: EvidenceReader,
        graph: KnowledgeGraph,
        embedder: Embedder,
        vectors: VectorStore,
        allow_simulated: bool = False,
    ) -> None:
        self.reader = reader
        self.graph, self.embedder = graph, embedder
        self.vectors, self.allow_simulated = vectors, allow_simulated

    def search(self, actor: Actor, question: str, limit: int = 5) -> dict[str, Any]:
        if actor.kind != "visitor" or not actor.store_id:
            raise DomainError("visitor_required")
        authority = self.reader.evidence(actor)
        if not authority:
            return {"items": [], "method": "none", "graph_status": "not_queried"}
        by_id = {str(item["id"]): item for item in authority}
        ids = list(by_id)
        details = self.reader.details(ids)
        topics = [topic for row in details for topic in row["topics"] if topic in question]
        question_terms = terms(question)
        scores: dict[str, float] = {}
        for row in details:
            item = by_id[str(row["version_id"])]
            tokens = terms(
                item["title"]
                + " "
                + item["content"]
                + " "
                + " ".join(row.get("guidance", {}).get("questions", []))
            )
            overlap = len(question_terms & tokens)
            if overlap:
                scores[str(row["version_id"])] = overlap / max(1, len(question_terms))
            if any(topic in question for topic in row["topics"]):
                scores[str(row["version_id"])] = scores.get(str(row["version_id"]), 0) + 1
        method = "lexical"
        try:
            vector = self.embedder.embed(question)
            rows = self.vectors.search(
                actor.tenant_id,
                actor.store_id,
                ids,
                vector,
                self.embedder.model,
                self.allow_simulated,
            )
            for row in rows:
                if str(row["version_id"]) not in by_id:
                    continue
                item = by_id[str(row["version_id"])]
                if row.get("model") != self.embedder.model or row.get("version") != item["version"]:
                    continue
                if row["content_hash"] != fingerprint(item["title"] + "\n" + item["content"]):
                    continue
                if row["score"] is not None and float(row["score"]) >= 0.5:
                    scores[str(row["version_id"])] = scores.get(str(row["version_id"]), 0) + float(
                        row["score"]
                    )
            method = "hybrid"
        except (GatewayError, VectorError):
            pass
        graph_status = "available"
        try:
            for version_id in self.graph.expand(actor.tenant_id, actor.store_id, ids, topics):
                if version_id in by_id:
                    scores[version_id] = scores.get(version_id, 0) + 0.25
        except Exception:
            graph_status = "unavailable"
        # Fresh authority query rejects withdrawal, expiry or newer publication during retrieval.
        fresh = {str(item["id"]): item for item in self.reader.evidence(actor)}
        ranked = sorted(scores, key=lambda key: (-scores[key], by_id[key]["knowledge_key"], key))
        return {
            "items": [fresh[key] for key in ranked if key in fresh][:limit],
            "method": method,
            "graph_status": graph_status,
        }
