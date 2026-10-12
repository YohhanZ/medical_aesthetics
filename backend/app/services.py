import hmac
from datetime import timedelta
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.config import Settings
from app.domain import Actor, DomainError, Repository, now
from app.knowledge_scope import MEDICAL_VISIBILITY_SQL
from app.knowledge_types import KnowledgeDetails
from app.security import digest, token, verify_password


class IdentityService:
    def __init__(self, repo: Repository, settings: Settings) -> None:
        self.repo = repo
        self.settings = settings

    def visitor_session(self, store_code: str) -> dict[str, Any]:
        store = self.repo.one(
            "SELECT s.* FROM store s JOIN tenant t ON t.id=s.tenant_id "
            "WHERE s.public_code=%s AND s.active AND (%s OR NOT(s.simulated OR t.simulated))",
            (store_code, self.settings.allow_simulated_data),
        )
        if not store:
            raise DomainError("store_unavailable", 404)
        visitor_id, session_id = str(uuid4()), str(uuid4())
        credential, csrf = token(), token()
        self.repo.execute(
            "INSERT INTO visitor(id,tenant_id,store_id) VALUES(%s,%s,%s)",
            (visitor_id, store["tenant_id"], store["id"]),
        )
        self.repo.execute(
            "INSERT INTO auth_session(id,tenant_id,visitor_id,store_id,token_hash,csrf_hash,"
            "expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                session_id,
                store["tenant_id"],
                visitor_id,
                store["id"],
                digest(credential),
                digest(csrf),
                now() + timedelta(hours=self.settings.session_hours),
            ),
        )
        actor = Actor(visitor_id, str(store["tenant_id"]), str(store["id"]), "visitor", session_id)
        return {
            "credential": credential,
            "csrf_token": csrf,
            "actor": actor,
            "simulated": store["simulated"],
        }

    def current_visitor(self, actor: Actor, csrf_cookie: str) -> dict[str, Any]:
        if actor.kind != "visitor":
            raise DomainError("visitor_required", 403)
        row = self.repo.one(
            "SELECT a.csrf_hash,a.expires_at,s.public_code,s.name,s.simulated "
            "FROM auth_session a JOIN store s ON (s.tenant_id,s.id)=(a.tenant_id,a.store_id) "
            "WHERE a.id=%s AND a.visitor_id=%s AND a.revoked_at IS NULL AND a.expires_at>now()",
            (actor.session_id, actor.id),
        )
        if not row:
            raise DomainError("unauthenticated", 401)
        if not csrf_cookie or not hmac.compare_digest(digest(csrf_cookie), row["csrf_hash"]):
            csrf_cookie = token()
            self.repo.execute(
                "UPDATE auth_session SET csrf_hash=%s WHERE id=%s",
                (digest(csrf_cookie), actor.session_id),
            )
        return {
            "visitor_id": actor.id,
            "store_id": actor.store_id,
            "store_code": row["public_code"],
            "store_name": row["name"],
            "simulated": row["simulated"],
            "csrf_token": csrf_cookie,
        }

    def authenticate(self, credential: str, kind: str, csrf: str | None = None) -> Actor:
        row = self.repo.one(
            "SELECT a.*,t.simulated AS tenant_simulated FROM auth_session a "
            "JOIN tenant t ON t.id=a.tenant_id WHERE token_hash=%s "
            "AND revoked_at IS NULL AND expires_at>now()",
            (digest(credential),),
        )
        if not row or (row["tenant_simulated"] and not self.settings.allow_simulated_data):
            raise DomainError("unauthenticated", 401)
        if kind == "visitor":
            if not row["visitor_id"]:
                raise DomainError("visitor_required", 403)
            store = self.repo.one(
                "SELECT id FROM store WHERE tenant_id=%s AND id=%s AND active "
                "AND (%s OR NOT simulated)",
                (row["tenant_id"], row["store_id"], self.settings.allow_simulated_data),
            )
            if not store:
                raise DomainError("store_unavailable", 403)
            if csrf is not None and not hmac.compare_digest(digest(csrf), row["csrf_hash"]):
                raise DomainError("csrf_invalid", 403)
            return Actor(
                str(row["visitor_id"]),
                str(row["tenant_id"]),
                str(row["store_id"]),
                "visitor",
                str(row["id"]),
            )
        staff = self.repo.one(
            "SELECT id FROM staff WHERE tenant_id=%s AND id=%s AND active "
            "AND (%s OR NOT simulated)",
            (row["tenant_id"], row["staff_id"], self.settings.allow_simulated_data),
        )
        if not staff:
            raise DomainError("staff_required", 403)
        return Actor(str(staff["id"]), str(row["tenant_id"]), None, "staff", str(row["id"]))

    def login(self, username: str, password: str, source: str, request_id: str) -> dict[str, str]:
        # Returns errors instead of raising so failed-attempt counters commit.
        bucket = digest(username.casefold() + "|" + source)
        self.repo.execute(
            "INSERT INTO login_bucket(bucket_hash,attempts,window_start) VALUES(%s,1,now()) "
            "ON CONFLICT(bucket_hash) DO UPDATE SET "
            "attempts=CASE WHEN login_bucket.window_start<now()-interval '15 minutes' "
            "THEN 1 ELSE login_bucket.attempts+1 END, "
            "window_start=CASE WHEN login_bucket.window_start<now()-interval '15 minutes' "
            "THEN now() ELSE login_bucket.window_start END",
            (bucket,),
        )
        limit = self.repo.one("SELECT attempts FROM login_bucket WHERE bucket_hash=%s", (bucket,))
        if limit and limit["attempts"] > 5:
            return {"error": "login_throttled"}
        staff = self.repo.one(
            "SELECT s.* FROM staff s JOIN tenant t ON t.id=s.tenant_id WHERE s.username=%s "
            "AND s.active AND (%s OR NOT(s.simulated OR t.simulated))",
            (username, self.settings.allow_simulated_data),
        )
        if not staff or not verify_password(password, staff["password_hash"]):
            return {"error": "invalid_credentials"}
        credential, session_id = token(), str(uuid4())
        self.repo.execute(
            "INSERT INTO auth_session(id,tenant_id,staff_id,token_hash,expires_at) "
            "VALUES(%s,%s,%s,%s,%s)",
            (
                session_id,
                staff["tenant_id"],
                staff["id"],
                digest(credential),
                now() + timedelta(hours=self.settings.session_hours),
            ),
        )
        self.repo.execute("DELETE FROM login_bucket WHERE bucket_hash=%s", (bucket,))
        actor = Actor(str(staff["id"]), str(staff["tenant_id"]), None, "staff", session_id)
        self.repo.audit(actor, "staff.session_create", session_id, request_id)
        return {"access_token": credential, "token_type": "bearer"}

    def revoke(self, actor: Actor) -> None:
        self.repo.execute(
            "UPDATE auth_session SET revoked_at=now() WHERE id=%s AND tenant_id=%s",
            (actor.session_id, actor.tenant_id),
        )

    def profile(self, actor: Actor) -> dict[str, Any]:
        if actor.kind != "staff":
            raise DomainError("staff_required")
        staff = self.repo.one(
            "SELECT id,username,simulated FROM staff WHERE tenant_id=%s AND id=%s AND active",
            (actor.tenant_id, actor.id),
        )
        if not staff:
            raise DomainError("staff_required")
        stores = self.repo.all(
            "SELECT s.id,s.name,s.simulated,array_agg(g.permission ORDER BY g.permission) "
            "AS permissions FROM store_grant g JOIN store s "
            "ON (s.tenant_id,s.id)=(g.tenant_id,g.store_id) "
            "WHERE g.tenant_id=%s AND g.staff_id=%s AND s.active "
            "AND (%s OR NOT s.simulated) GROUP BY s.id ORDER BY s.name",
            (actor.tenant_id, actor.id, self.settings.allow_simulated_data),
        )
        return {**staff, "stores": stores}


class ConversationService:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def create(self, actor: Actor, request_id: str) -> dict[str, Any]:
        if actor.kind != "visitor":
            raise DomainError("visitor_required")
        thread_id = str(uuid4())
        self.repo.execute(
            "INSERT INTO conversation(id,tenant_id,store_id,visitor_id) VALUES(%s,%s,%s,%s)",
            (thread_id, actor.tenant_id, actor.store_id, actor.id),
        )
        self.repo.audit(actor, "thread.create", thread_id, request_id)
        return {"thread_id": thread_id}

    def get(self, actor: Actor, thread_id: str) -> dict[str, Any]:
        row = self.repo.one(
            "SELECT id AS thread_id,created_at FROM conversation WHERE id=%s "
            "AND tenant_id=%s AND store_id=%s AND visitor_id=%s",
            (thread_id, actor.tenant_id, actor.store_id, actor.id),
        )
        if not row or actor.kind != "visitor":
            raise DomainError("thread_not_found", 404)
        return row


class KnowledgeService:
    def __init__(self, repo: Repository, settings: Settings) -> None:
        self.repo = repo
        self.settings = settings

    def grant(self, actor: Actor, store_id: str, permission: str) -> None:
        grant = self.repo.one(
            "SELECT g.staff_id FROM store_grant g JOIN store s "
            "ON (s.tenant_id,s.id)=(g.tenant_id,g.store_id) "
            "JOIN staff u ON (u.tenant_id,u.id)=(g.tenant_id,g.staff_id) "
            "WHERE g.tenant_id=%s AND g.staff_id=%s AND g.store_id=%s AND g.permission=%s "
            "AND s.active AND u.active AND (%s OR NOT(s.simulated OR u.simulated))",
            (actor.tenant_id, actor.id, store_id, permission, self.settings.allow_simulated_data),
        )
        if actor.kind != "staff" or not grant:
            raise DomainError("store_permission_denied")

    def list_versions(self, actor: Actor, store_id: str, limit: int, offset: int) -> dict[str, Any]:
        profile = IdentityService(self.repo, self.settings).profile(actor)
        if not any(
            str(store["id"]) == store_id
            and any(p.startswith("knowledge_") for p in store["permissions"])
            for store in profile["stores"]
        ):
            raise DomainError("store_permission_denied")
        params = (actor.tenant_id, store_id)
        count = self.repo.one(
            "SELECT count(*) AS total FROM knowledge_version WHERE tenant_id=%s AND store_id=%s",
            params,
        )
        items = self.repo.all(
            "SELECT k.id,k.knowledge_key,k.version,k.category,k.title,k.content,k.source,"
            "k.author_id,k.simulated,k.valid_until,k.created_at,k.status,r.reviewer_id,"
            "r.reason AS review_reason,p.state AS projection_state "
            "FROM knowledge_version k LEFT JOIN knowledge_review r ON r.version_id=k.id "
            "LEFT JOIN publication p ON p.version_id=k.id "
            "WHERE k.tenant_id=%s AND k.store_id=%s ORDER BY k.created_at DESC,k.id "
            "LIMIT %s OFFSET %s",
            (*params, limit, offset),
        )
        return {"items": items, "total": count["total"] if count else 0}

    def create(
        self, actor: Actor, store_id: str, data: dict[str, Any], request_id: str
    ) -> dict[str, Any]:
        self.grant(actor, store_id, "knowledge_author")
        if data["simulated"] and not self.settings.allow_simulated_data:
            raise DomainError("simulation_disabled")
        if data["valid_until"] <= now():
            raise DomainError("knowledge_expired", 422)
        # Serialize version assignment for this exact tenant/store/key.
        self.repo.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"{actor.tenant_id}/{store_id}/{data['knowledge_key']}",),
        )
        latest = self.repo.one(
            "SELECT COALESCE(MAX(version),0)+1 AS version FROM knowledge_version "
            "WHERE tenant_id=%s AND store_id=%s AND knowledge_key=%s",
            (actor.tenant_id, store_id, data["knowledge_key"]),
        )
        assert latest is not None
        version_id = str(uuid4())
        self.repo.execute(
            "INSERT INTO knowledge_version(id,tenant_id,store_id,knowledge_key,version,category,"
            "title,content,source,author_id,simulated,valid_until) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                version_id,
                actor.tenant_id,
                store_id,
                data["knowledge_key"],
                latest["version"],
                data["category"],
                data["title"],
                data["content"],
                data["source"],
                actor.id,
                data["simulated"],
                data["valid_until"],
            ),
        )
        details = KnowledgeDetails.model_validate(
            data.get("details")
            or {"audience": "internal" if data["category"] == "communication" else "public"}
        )
        if data["category"] == "communication" and details.audience != "internal":
            raise DomainError("internal_strategy_required", 422)
        self.repo.execute(
            "INSERT INTO knowledge_detail(version_id,audience,topics,entities,relations,guidance) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (
                version_id,
                details.audience,
                details.topics,
                Jsonb([entity.model_dump() for entity in details.entities]),
                Jsonb([relation.model_dump() for relation in details.relations]),
                Jsonb(
                    details.model_dump(
                        mode="json", exclude={"audience", "topics", "entities", "relations"}
                    )
                ),
            ),
        )
        self.repo.audit(actor, "knowledge.create", version_id, request_id)
        return {"version_id": version_id, "version": latest["version"], "status": "draft"}

    def locked(self, actor: Actor, store_id: str, version_id: str) -> dict[str, Any]:
        row = self.repo.one(
            "SELECT * FROM knowledge_version WHERE id=%s AND tenant_id=%s AND store_id=%s "
            "FOR UPDATE",
            (version_id, actor.tenant_id, store_id),
        )
        if not row:
            raise DomainError("knowledge_not_found", 404)
        return row

    def review(
        self,
        actor: Actor,
        store_id: str,
        version_id: str,
        approved: bool,
        reason: str,
        request_id: str,
    ) -> dict[str, str]:
        self.grant(actor, store_id, "knowledge_review")
        row = self.locked(actor, store_id, version_id)
        if str(row["author_id"]) == actor.id:
            raise DomainError("independent_review_required")
        if row["status"] != "draft":
            raise DomainError("review_state_conflict", 409)
        # M1 has no real credential verification, hence no real medical approval path.
        if approved and row["category"] == "medical" and not self.demo_medical_version(row):
            raise DomainError("medical_verification_required", 409)
        if approved and row["category"] == "medical":
            reason = "模拟公开科普演练复核，不代表真实医学批准；" + reason
        simulated_review = self.settings.environment != "production"
        if simulated_review and not row["simulated"]:
            raise DomainError("real_content_requires_real_review", 409)
        self.repo.execute(
            "INSERT INTO knowledge_review(version_id,tenant_id,store_id,reviewer_id,approved,"
            "simulated,reason) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (version_id, actor.tenant_id, store_id, actor.id, approved, simulated_review, reason),
        )
        status = "approved" if approved else "rejected"
        self.repo.execute(
            "UPDATE knowledge_version SET status=%s WHERE id=%s", (status, version_id)
        )
        self.repo.audit(actor, f"knowledge.{status}", version_id, request_id)
        return {"status": status}

    def publish(
        self, actor: Actor, store_id: str, version_id: str, request_id: str
    ) -> dict[str, str]:
        self.grant(actor, store_id, "knowledge_publish")
        row = self.locked(actor, store_id, version_id)
        if row["status"] in ("publishing", "published"):
            return {"status": row["status"]}
        if row["status"] != "approved" or row["valid_until"] <= now():
            raise DomainError("publication_not_allowed", 409)
        review = self.repo.one("SELECT * FROM knowledge_review WHERE version_id=%s", (version_id,))
        if (
            not review
            or not review["approved"]
            or str(review["reviewer_id"]) == str(row["author_id"])
        ):
            raise DomainError("independent_review_required")
        if (row["simulated"] or review["simulated"]) and not self.settings.allow_simulated_data:
            raise DomainError("simulation_disabled")
        if row["category"] == "medical" and not (
            review["simulated"] and self.demo_medical_version(row)
        ):
            raise DomainError("medical_verification_required", 409)
        self.repo.execute(
            "INSERT INTO publication(version_id,tenant_id,store_id,state) "
            "VALUES(%s,%s,%s,'pending')",
            (version_id, actor.tenant_id, store_id),
        )
        self.repo.execute(
            "UPDATE knowledge_version SET status='publishing' WHERE id=%s", (version_id,)
        )
        self.repo.execute(
            "INSERT INTO outbox(tenant_id,store_id,version_id,topic) VALUES(%s,%s,%s,'publish')",
            (actor.tenant_id, store_id, version_id),
        )
        self.repo.audit(actor, "knowledge.publish_requested", version_id, request_id)
        return {"status": "publishing"}

    def withdraw(
        self, actor: Actor, store_id: str, version_id: str, request_id: str
    ) -> dict[str, str]:
        self.grant(actor, store_id, "knowledge_publish")
        self.locked(actor, store_id, version_id)
        self.repo.execute(
            "UPDATE knowledge_version SET status='withdrawn' WHERE id=%s", (version_id,)
        )
        self.repo.execute(
            "UPDATE publication SET state='withdrawn' WHERE version_id=%s", (version_id,)
        )
        self.repo.execute(
            "INSERT INTO outbox(tenant_id,store_id,version_id,topic) VALUES(%s,%s,%s,'withdraw') "
            "ON CONFLICT(version_id,topic) DO NOTHING",
            (actor.tenant_id, store_id, version_id),
        )
        self.repo.audit(actor, "knowledge.withdraw", version_id, request_id)
        return {"status": "withdrawn"}

    def evidence(self, actor: Actor) -> list[dict[str, Any]]:
        # Authority gate remains necessary even after vector/Neo4j retrieval in M2.
        return self.repo.all(
            "SELECT k.id,k.knowledge_key,k.version,k.title,k.content,k.source,"
            "k.simulated,k.valid_until,d.guidance->>'review_scope' AS review_scope "
            "FROM knowledge_version k JOIN knowledge_review r ON r.version_id=k.id "
            "JOIN publication p ON p.version_id=k.id "
            "JOIN knowledge_detail d ON d.version_id=k.id AND d.audience='public' "
            "JOIN vector_projection vp ON vp.version_id=k.id "
            "JOIN store s ON (s.tenant_id,s.id)=(k.tenant_id,k.store_id) "
            "JOIN tenant t ON t.id=k.tenant_id "
            "WHERE k.tenant_id=%s AND k.store_id=%s AND k.status='published' "
            "AND " + MEDICAL_VISIBILITY_SQL + "AND k.valid_until>now() AND r.approved "
            "AND r.reviewer_id<>k.author_id AND p.state='ready' "
            "AND p.vector_ready AND p.graph_ready "
            "AND vp.state='ready' AND vp.collection_name=%s "
            "AND vp.content_hash=encode(sha256(convert_to("
            "k.title || chr(10) || k.content,'UTF8')),'hex') "
            "AND (%s OR NOT(k.simulated OR r.simulated)) "
            "AND NOT EXISTS(SELECT 1 FROM knowledge_version newer "
            "WHERE newer.tenant_id=k.tenant_id "
            "AND newer.store_id=k.store_id AND newer.knowledge_key=k.knowledge_key "
            "AND newer.version>k.version "
            "AND newer.status IN ('publishing','published','withdrawn')) "
            "ORDER BY k.knowledge_key",
            (
                actor.tenant_id,
                actor.store_id,
                self.settings.demo_medical_enabled,
                self.settings.milvus_collection,
                self.settings.allow_simulated_data,
            ),
        )

    def demo_medical_version(self, row: dict[str, Any]) -> bool:
        if not self.settings.demo_medical_enabled or not row["simulated"]:
            return False
        scoped = self.repo.one(
            "SELECT d.guidance FROM knowledge_detail d JOIN knowledge_version k "
            "ON k.id=d.version_id JOIN store s ON (s.tenant_id,s.id)=(k.tenant_id,k.store_id) "
            "JOIN tenant t ON t.id=k.tenant_id WHERE k.id=%s AND s.simulated AND t.simulated "
            "AND d.audience='public' AND d.guidance->>'review_scope'='demo_education'",
            (row["id"],),
        )
        if not scoped:
            return False
        details = KnowledgeDetails.model_validate(scoped["guidance"])
        return details.review_scope == "demo_education"
