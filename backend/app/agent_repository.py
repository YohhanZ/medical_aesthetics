"""PostgreSQL authority, message idempotency, leases, memories and metadata-only traces."""

from typing import Any, Protocol
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from psycopg.types.json import Jsonb

from app.config import Settings
from app.customer import RECALL, CustomerService, is_preference_statement, personalize_answer
from app.db import PostgresRepository, transaction
from app.domain import Actor, DomainError
from app.model_gateway import fingerprint
from app.services import ConversationService, KnowledgeService


class AgentStore(Protocol):
    settings: Settings
    actor: Actor
    thread_id: str

    def checkpointer(self, run_id: str, lease: str) -> BaseCheckpointSaver[int]: ...
    def history(self, limit: int, offset: int, recent: bool = False) -> list[dict[str, Any]]: ...
    def run(self, run_id: str) -> dict[str, Any]: ...
    def check(self, run_id: str, lease: str) -> None: ...
    def claim(self, message_id: str, question: str) -> dict[str, Any]: ...
    def context(self, run_id: str) -> tuple[str, list[dict[str, Any]], dict[str, Any]]: ...
    def finish(
        self,
        run_id: str,
        lease: str,
        result: dict[str, Any],
        memory: dict[str, Any],
        exportable: bool,
    ) -> dict[str, Any]: ...
    def trace(self, run_id: str, lease: str, node: str, elapsed: int, outcome: str) -> None: ...
    def fail(self, run_id: str, lease: str, code: str) -> None: ...


class PostgresAgentStore:
    def __init__(self, settings: Settings, actor: Actor, thread_id: str) -> None:
        self.settings, self.actor, self.thread_id = settings, actor, thread_id

    def checkpointer(self, run_id: str, lease: str) -> BaseCheckpointSaver[int]:
        from app.agent_checkpoint import ScopedCheckpointSaver

        return ScopedCheckpointSaver(self, run_id, lease)

    def authorize(self, repo: PostgresRepository) -> None:
        a = self.actor
        row = repo.one(
            "SELECT a.id FROM auth_session a JOIN store s "
            "ON (s.tenant_id,s.id)=(a.tenant_id,a.store_id) JOIN tenant t ON t.id=a.tenant_id "
            "WHERE a.id=%s AND a.visitor_id=%s AND a.tenant_id=%s AND a.store_id=%s "
            "AND a.revoked_at IS NULL AND a.expires_at>now() AND s.active "
            "AND (%s OR NOT(s.simulated OR t.simulated))",
            (a.session_id, a.id, a.tenant_id, a.store_id, self.settings.allow_simulated_data),
        )
        if not row or a.kind != "visitor":
            raise DomainError("unauthenticated", 401)
        if self.settings.customer_login_required:
            CustomerService(repo, self.settings, a).require_account()
        ConversationService(repo).get(a, self.thread_id)

    def owns(self, repo: PostgresRepository, run_id: str, lease: str) -> None:
        self.authorize(repo)
        row = repo.one(
            "SELECT id FROM agent_run WHERE id=%s AND thread_id=%s "
            "AND status='running' AND lease_token=%s AND lease_until>now() FOR UPDATE",
            (run_id, self.thread_id, lease),
        )
        if not row:
            raise DomainError("run_lease_lost", 409)

    def check(self, run_id: str, lease: str) -> None:
        with transaction(self.settings.database_url) as repo:
            self.owns(repo, run_id, lease)

    def claim(self, message_id: str, question: str) -> dict[str, Any]:
        with transaction(self.settings.database_url) as repo:
            self.authorize(repo)
            repo.one("SELECT id FROM conversation WHERE id=%s FOR UPDATE", (self.thread_id,))
            existing = repo.one(
                "SELECT * FROM agent_run WHERE thread_id=%s AND message_id=%s",
                (self.thread_id, message_id),
            )
            if existing and existing["request_hash"] != fingerprint(question):
                raise DomainError("message_id_conflict", 409)
            if existing and existing["status"] == "completed":
                return existing
            active = repo.one(
                "SELECT id,lease_until>now() AS active FROM agent_run "
                "WHERE thread_id=%s AND status='running' ORDER BY created_at LIMIT 1",
                (self.thread_id,),
            )
            if active and (not existing or active["id"] != existing["id"]):
                raise DomainError(
                    "conversation_busy" if active["active"] else "recovery_required", 409
                )
            if active and active["active"]:
                raise DomainError("conversation_busy", 409)
            lease = str(uuid4())
            if existing:
                row = repo.one(
                    "UPDATE agent_run SET status='running',lease_token=%s,"
                    "lease_until=now()+interval '90 seconds',fence=fence+1,error_code=NULL "
                    "WHERE id=%s RETURNING *",
                    (lease, existing["id"]),
                )
                assert row
                return row
            count = repo.one(
                "SELECT count(*) AS n FROM agent_run WHERE visitor_id=%s "
                "AND created_at>now()-interval '1 minute'",
                (self.actor.id,),
            )
            if count and count["n"] >= 20:
                raise DomainError("conversation_rate_limited", 429)
            count = repo.one(
                "SELECT count(*) AS n FROM agent_run WHERE thread_id=%s", (self.thread_id,)
            )
            if count and count["n"] >= 500:
                raise DomainError("conversation_limit", 429)
            run_id = str(uuid4())
            row = repo.one(
                "INSERT INTO agent_run(id,tenant_id,store_id,visitor_id,thread_id,message_id,"
                "request_hash,status,lease_token,lease_until) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,'running',%s,now()+interval '90 seconds') RETURNING *",
                (
                    run_id,
                    self.actor.tenant_id,
                    self.actor.store_id,
                    self.actor.id,
                    self.thread_id,
                    message_id,
                    fingerprint(question),
                    lease,
                ),
            )
            repo.execute(
                "INSERT INTO agent_message(id,run_id,role,content) VALUES(%s,%s,'user',%s)",
                (str(uuid4()), run_id, question),
            )
            customer = CustomerService(repo, self.settings, self.actor).account()
            if customer and customer["memory_enabled"]:
                repo.execute(
                    "UPDATE agent_run SET customer_memory_generation=%s WHERE id=%s",
                    (customer["memory_generation"], run_id),
                )
            assert row
            return row

    def context(self, run_id: str) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        with transaction(self.settings.database_url) as repo:
            self.authorize(repo)
            current = repo.one(
                "SELECT m.content FROM agent_message m JOIN agent_run r ON r.id=m.run_id "
                "WHERE r.id=%s AND r.thread_id=%s AND m.role='user'",
                (run_id, self.thread_id),
            )
            if not current:
                raise DomainError("run_not_found", 404)
            rows = repo.all(
                "SELECT m.id,m.content,r.result FROM agent_message m "
                "JOIN agent_run r ON r.id=m.run_id "
                "WHERE r.thread_id=%s AND r.id<>%s AND r.status='completed' "
                "AND m.role='user' AND m.exportable ORDER BY r.created_at DESC LIMIT 6",
                (self.thread_id, run_id),
            )
            memory = repo.one(
                "SELECT snapshot FROM agent_memory WHERE thread_id=%s", (self.thread_id,)
            )
            snapshot = dict(memory["snapshot"]) if memory else {}
            customer = CustomerService(repo, self.settings, self.actor)
            snapshot["_customer_preferences"] = [
                {"key": row["key"], "value": row["value"]} for row in customer.memories()
            ]
            if not snapshot.get("first_topic"):
                # Existing threads have no topic references yet. Resolve only their own public
                # completed messages; 500 is the existing per-thread run limit.
                snapshot["_initial_public_sources"] = repo.all(
                    "SELECT r.id AS run_id,r.message_id,m.content FROM agent_message m "
                    "JOIN agent_run r ON r.id=m.run_id WHERE r.thread_id=%s "
                    "AND r.id<>%s AND r.status='completed' AND m.role='user' AND m.exportable "
                    "ORDER BY r.created_at,r.id LIMIT 500",
                    (self.thread_id, run_id),
                )
            sources = {}
            for field in ("first_topic", "active_topic"):
                record = snapshot.get(field)
                if not isinstance(record, dict):
                    continue
                source = repo.one(
                    "SELECT m.id,m.content FROM agent_message m JOIN agent_run r ON r.id=m.run_id "
                    "WHERE r.id::text=%s AND r.thread_id=%s AND r.status='completed' "
                    "AND r.message_id::text=%s AND m.role='user' AND (m.exportable OR "
                    "(r.result->>'intent'='support' AND r.result->>'handoff_reason'=''))",
                    (record.get("source_run_id"), self.thread_id, record.get("source_message_id")),
                )
                if source:
                    sources[record["source_run_id"]] = source
            snapshot["_topic_sources"] = sources
            return (
                str(current["content"]),
                list(reversed(rows)),
                snapshot,
            )

    def finish(
        self,
        run_id: str,
        lease: str,
        result: dict[str, Any],
        memory: dict[str, Any],
        exportable: bool,
    ) -> dict[str, Any]:
        with transaction(self.settings.database_url) as repo:
            self.owns(repo, run_id, lease)
            customer = CustomerService(repo, self.settings, self.actor)
            source = repo.one(
                "SELECT content FROM agent_message WHERE run_id=%s AND role='user'",
                (run_id,),
            )
            # Recheck consent/deletion after model or sandbox work, before returning memories.
            repo.one("SELECT id FROM visitor WHERE id=%s FOR UPDATE", (self.actor.id,))
            if result["evidence_ids"]:
                repo.all(
                    "SELECT id FROM knowledge_version WHERE id=ANY(%s::uuid[]) FOR SHARE",
                    (result["evidence_ids"],),
                )
                allowed = {
                    str(row["id"])
                    for row in KnowledgeService(repo, self.settings).evidence(self.actor)
                }
                if not set(result["evidence_ids"]) <= allowed:
                    from app.agent_policy import handoff_answer

                    result.update(
                        answer=handoff_answer("evidence_changed"),
                        public_answer="",
                        evidence_ids=[],
                        evidence=[],
                        handoff_reason="evidence_changed",
                        mode="handoff",
                    )
            if result["handoff_reason"]:
                ticket_id = str(uuid4())
                repo.execute(
                    "INSERT INTO handoff_ticket(id,run_id,reason) VALUES(%s,%s,%s) "
                    "ON CONFLICT(run_id) DO NOTHING",
                    (ticket_id, run_id, result["handoff_reason"]),
                )
                ticket = repo.one("SELECT id FROM handoff_ticket WHERE run_id=%s", (run_id,))
                assert ticket
                result["handoff"] = {
                    "ticket_id": str(ticket["id"]),
                    "status": "waiting",
                    "connected": False,
                }
            if source:
                personalize_answer(source["content"], result, customer.memories())
                exportable = bool(
                    exportable
                    and not (
                        RECALL.search(source["content"])
                        or is_preference_statement(source["content"])
                    )
                )
            repo.execute(
                "INSERT INTO agent_message(id,run_id,role,content) VALUES(%s,%s,'assistant',%s) "
                "ON CONFLICT(run_id,role) DO NOTHING",
                (str(uuid4()), run_id, result["answer"]),
            )
            repo.execute(
                "UPDATE agent_message SET exportable=%s WHERE run_id=%s AND role='user'",
                (exportable, run_id),
            )
            repo.execute(
                "INSERT INTO agent_memory(thread_id,snapshot) VALUES(%s,%s) "
                "ON CONFLICT(thread_id) DO UPDATE SET snapshot=excluded.snapshot,"
                "version=agent_memory.version+1,updated_at=now()",
                (self.thread_id, Jsonb(memory)),
            )
            repo.execute(
                "UPDATE agent_run SET status='completed',result=%s WHERE id=%s",
                (Jsonb(result), run_id),
            )
            if source:
                customer.capture(
                    source["content"],
                    self.thread_id,
                    run_id,
                    result["handoff_reason"]
                    not in (
                        "urgent_health",
                        "emotional_crisis",
                        "private_record",
                        "unauthorized_request",
                    ),
                )
            customer.behavior("consultation_started", self.thread_id)
            repo.audit(self.actor, "agent.completed", run_id, run_id)
        return result

    def trace(self, run_id: str, lease: str, node: str, elapsed: int, outcome: str) -> None:
        with transaction(self.settings.database_url) as repo:
            self.owns(repo, run_id, lease)
            repo.execute(
                "INSERT INTO agent_trace(run_id,node,elapsed_ms,outcome) VALUES(%s,%s,%s,%s)",
                (run_id, node, elapsed, outcome),
            )

    def fail(self, run_id: str, lease: str, code: str) -> None:
        with transaction(self.settings.database_url) as repo:
            repo.execute(
                "UPDATE agent_run SET status='failed',error_code=%s WHERE id=%s "
                "AND thread_id=%s AND lease_token=%s AND status='running'",
                (code, run_id, self.thread_id, lease),
            )

    def history(self, limit: int, offset: int, recent: bool = False) -> list[dict[str, Any]]:
        with transaction(self.settings.database_url) as repo:
            self.authorize(repo)
            order = "r.created_at DESC,m.role ASC" if recent else "r.created_at,m.role DESC"
            rows = repo.all(
                "SELECT m.id,m.role,m.content,r.message_id,r.id AS run_id,r.status,r.result "
                "FROM agent_message m JOIN agent_run r ON r.id=m.run_id "
                f"WHERE r.thread_id=%s ORDER BY {order} LIMIT %s OFFSET %s",
                (self.thread_id, limit, offset),
            )
            return list(reversed(rows)) if recent else rows

    def run(self, run_id: str) -> dict[str, Any]:
        with transaction(self.settings.database_url) as repo:
            self.authorize(repo)
            row = repo.one(
                "SELECT id,status,result,error_code FROM agent_run WHERE id=%s AND thread_id=%s",
                (run_id, self.thread_id),
            )
            if not row:
                raise DomainError("run_not_found", 404)
            row["trace"] = repo.all(
                "SELECT node,elapsed_ms,outcome FROM agent_trace "
                "WHERE run_id=%s ORDER BY id LIMIT 100",
                (run_id,),
            )
            return row
