"""Scoped drafts, contact verification, explicit consent and atomic appointment submission."""

import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet
from psycopg.types.json import Jsonb

from app.agent_policy import classify
from app.booking_models import CONFIRMATION_TEXT, ConfirmInput, DraftInput
from app.booking_projection import current_proposal
from app.config import Settings
from app.db import transaction
from app.domain import Actor, DomainError, Repository, now
from app.services import KnowledgeService
from app.sms_gateway import Delivery, SmsGateway, sms_gateway


class BookingService:
    def __init__(self, repo: Repository, settings: Settings, actor: Actor, thread: str) -> None:
        self.repo, self.settings, self.actor, self.thread = repo, settings, actor, thread

    def scope(self) -> dict[str, Any]:
        a = self.actor
        row = self.repo.one(
            "SELECT s.name,s.simulated OR t.simulated AS simulated FROM auth_session a "
            "JOIN store s ON (s.tenant_id,s.id)=(a.tenant_id,a.store_id) JOIN tenant "
            "t ON t.id=a.tenant_id "
            "WHERE a.id=%s AND a.visitor_id=%s AND a.tenant_id=%s AND a.store_id=%s "
            "AND a.revoked_at IS NULL AND a.expires_at>now() AND s.active "
            "AND (%s OR NOT(s.simulated OR t.simulated)) FOR UPDATE OF a FOR SHARE OF s,t",
            (a.session_id, a.id, a.tenant_id, a.store_id, self.settings.allow_simulated_data),
        )
        if not row or a.kind != "visitor":
            raise DomainError("unauthenticated", 401)
        if not self.repo.one(
            "SELECT id FROM conversation WHERE id=%s AND tenant_id=%s AND store_id=%s "
            "AND visitor_id=%s FOR UPDATE",
            (self.thread, a.tenant_id, a.store_id, a.id),
        ):
            raise DomainError("thread_not_found", 404)
        return row

    def configured(self) -> bool:
        return self.settings.booking_sms_provider != "disabled"

    def cipher(self) -> Fernet:
        if not self.configured():
            raise DomainError("verification_not_configured", 503)
        return Fernet(self.settings.booking_encryption_key.get_secret_value().encode())

    def hashed(self, value: str) -> str:
        return hmac.new(
            self.settings.booking_hmac_key.get_secret_value().encode(),
            value.encode(),
            hashlib.sha256,
        ).hexdigest()

    def decrypt(self, value: str) -> dict[str, Any]:
        return dict(json.loads(self.cipher().decrypt(value.encode())))

    def eligible_run(self) -> str | None:
        row = self.repo.one(
            "SELECT id,status,result FROM agent_run WHERE thread_id=%s ORDER BY creat"
            "ed_at DESC,id DESC LIMIT 1",
            (self.thread,),
        )
        if (
            row
            and row["status"] == "completed"
            and row["result"].get("handoff_reason") == "visit_request"
            and row["result"].get("intent") == "visit_interest"
        ):
            return str(row["id"])
        return None

    def eligible(self, trigger: str) -> None:
        if self.eligible_run() != trigger:
            raise DomainError("booking_offer_changed", 409)

    def replay(self, operation: str, key: str, payload: str) -> dict[str, Any] | None:
        a = self.actor
        row = self.repo.one(
            "SELECT request_hash,result FROM booking_idempotency WHERE tenant_id=%s A"
            "ND visitor_id=%s AND operation=%s AND request_key=%s",
            (a.tenant_id, a.id, operation, key),
        )
        if row and not hmac.compare_digest(row["request_hash"], self.hashed(payload)):
            raise DomainError("booking_key_conflict", 409)
        return row["result"] if row else None

    def record(self, operation: str, key: str, payload: str, result: dict[str, Any]) -> None:
        a = self.actor
        self.repo.execute(
            "INSERT INTO booking_idempotency(tenant_id,store_id,visitor_id,operation,"
            "request_key,request_hash,result) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (a.tenant_id, a.store_id, a.id, operation, key, self.hashed(payload), Jsonb(result)),
        )

    def project(self, project_id: str | None) -> str | None:
        if not project_id:
            return None
        self.repo.one("SELECT id FROM knowledge_version WHERE id=%s FOR SHARE", (project_id,))
        row = next(
            (
                row
                for row in KnowledgeService(self.repo, self.settings).evidence(self.actor)
                if str(row["id"]) == project_id and row["knowledge_key"].startswith("catalog-")
            ),
            None,
        )
        if not row:
            raise DomainError("project_unavailable", 404)
        return str(row["title"])

    def policy(self) -> dict[str, Any]:
        versions = self.repo.all(
            "SELECT id,category FROM knowledge_version WHERE tenant_id=%s AND store_id=%s "
            "AND knowledge_key=%s ORDER BY version FOR SHARE",
            (self.actor.tenant_id, self.actor.store_id, self.settings.booking_policy_key),
        )
        allowed_ids = {str(row["id"]) for row in versions if row["category"] == "operational"}
        rows = [
            row
            for row in KnowledgeService(self.repo, self.settings).evidence(self.actor)
            if row["knowledge_key"] == self.settings.booking_policy_key
            and str(row["id"]) in allowed_ids
        ]
        if not rows:
            raise DomainError("booking_policy_unavailable", 409)
        row = max(rows, key=lambda value: value["version"])
        return {
            "id": str(row["id"]),
            "title": row["title"],
            "version": row["version"],
            "content": row["content"],
            "source": row["source"],
            "simulated": row["simulated"],
        }

    def draft(self, draft_id: str) -> dict[str, Any]:
        a = self.actor
        row = self.repo.one(
            "SELECT * FROM appointment_draft WHERE id=%s AND thread_id=%s AND tenant_"
            "id=%s AND store_id=%s AND visitor_id=%s FOR UPDATE",
            (draft_id, self.thread, a.tenant_id, a.store_id, a.id),
        )
        if not row:
            raise DomainError("draft_not_found", 404)
        return row

    def active(self, row: dict[str, Any]) -> None:
        if row["status"] != "active" or row["expires_at"] <= now():
            raise DomainError("draft_expired_or_replaced", 409)
        self.eligible(str(row["trigger_run_id"]))
        if self.decrypt(row["snapshot_cipher"])["policy"]["id"] != self.policy()["id"]:
            raise DomainError("booking_policy_changed", 409)
        self.project(str(row["project_version_id"]) if row["project_version_id"] else None)

    def draft_view(self, row: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.decrypt(row["snapshot_cipher"])
        return {
            "id": str(row["id"]),
            "request_key": str(row["request_key"]),
            "snapshot_hash": row["snapshot_hash"],
            "name": snapshot["name"],
            "phone_masked": snapshot["phone"][:3] + "****" + snapshot["phone"][-4:],
            "intention": snapshot["intention"],
            "desired_at": snapshot["desired_at"],
            "project_title": snapshot["project_title"],
            "store_name": snapshot["store_name"],
            "expires_at": row["expires_at"].isoformat(),
            "status": row["status"],
            "simulated": row["simulated"],
            "trigger_run_id": str(row["trigger_run_id"]),
            "policy": snapshot["policy"],
        }

    def create(self, data: DraftInput, request_id: str) -> dict[str, Any]:
        store = self.scope()
        self.cipher()
        payload = self.thread + "|" + data.model_dump_json()
        replay = self.replay("draft", str(data.request_key), payload)
        if replay:
            return self.draft_view(self.draft(replay["draft_id"]))
        self.eligible(str(data.trigger_run_id))
        if self.repo.one(
            "SELECT id FROM appointment_draft WHERE trigger_run_id=%s AND status='submitted'",
            (data.trigger_run_id,),
        ):
            raise DomainError("booking_already_submitted", 409)
        if not now() + timedelta(minutes=15) < data.desired_at < now() + timedelta(days=90):
            raise DomainError("booking_time_invalid", 422)
        if classify(data.intention, True)["reason"]:
            raise DomainError("booking_intention_requires_human", 422)
        count = self.repo.one(
            "SELECT count(*) AS n FROM appointment_draft WHERE visitor_id=%s AND crea"
            "ted_at>now()-interval '1 day'",
            (self.actor.id,),
        )
        if count and count["n"] >= 20:
            raise DomainError("booking_rate_limited", 429)
        project_title = self.project(
            str(data.project_version_id) if data.project_version_id else None
        )
        policy = self.policy()
        draft_id = str(uuid4())
        snapshot = {
            "name": data.name,
            "phone": data.phone,
            "desired_at": data.desired_at.isoformat(),
            "intention": data.intention,
            "project_title": project_title,
            "project_version_id": str(data.project_version_id) if data.project_version_id else None,
            "store_name": store["name"],
            "thread_id": self.thread,
            "store_id": self.actor.store_id,
            "trigger_run_id": str(data.trigger_run_id),
            "policy": policy,
        }
        raw = json.dumps(snapshot, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.repo.execute(
            "UPDATE appointment_draft SET status='superseded' WHERE thread_id=%s AND "
            "status='active'",
            (self.thread,),
        )
        a = self.actor
        self.repo.execute(
            "INSERT INTO appointment_draft(id,tenant_id,store_id,visitor_id,thread_id,"
            "trigger_run_id,request_key,snapshot_cipher,snapshot_hash,phone_hash,"
            "project_version_id,status,simulated,expires_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s)",
            (
                draft_id,
                a.tenant_id,
                a.store_id,
                a.id,
                self.thread,
                data.trigger_run_id,
                data.request_key,
                self.cipher().encrypt(raw.encode()).decode(),
                self.hashed(raw),
                self.hashed("phone:" + data.phone),
                data.project_version_id,
                store["simulated"]
                or policy["simulated"]
                or self.settings.booking_sms_provider == "simulated",
                now() + timedelta(minutes=30),
            ),
        )
        self.record("draft", str(data.request_key), payload, {"draft_id": draft_id})
        self.repo.audit(a, "appointment.draft_create", draft_id, request_id)
        return self.draft_view(self.draft(draft_id))

    def challenge(self, verification_id: str) -> dict[str, Any]:
        a = self.actor
        row = self.repo.one(
            "SELECT v.* FROM contact_verification v JOIN appointment_draft d ON d.id="
            "v.draft_id WHERE v.id=%s AND d.thread_id=%s AND v.tenant_id=%s AND v.sto"
            "re_id=%s AND v.visitor_id=%s FOR UPDATE OF v",
            (verification_id, self.thread, a.tenant_id, a.store_id, a.id),
        )
        if not row:
            raise DomainError("verification_not_found", 404)
        return row

    def verification_view(self, row: dict[str, Any]) -> dict[str, Any]:
        result = {
            "id": str(row["id"]),
            "request_key": str(row["request_key"]),
            "draft_id": str(row["draft_id"]),
            "delivery_state": row["delivery_state"],
            "expires_at": row["expires_at"].isoformat(),
            "verified": bool(
                row["verified_at"] and row["verified_until"] > now() and not row["consumed_at"]
            ),
            "simulated": row["simulated"],
            "attempts_remaining": 5 - row["attempts"],
        }
        if (
            row["simulated"]
            and self.settings.environment != "production"
            and row["delivery_state"] == "sent"
            and row["expires_at"] > now()
            and not row["consumed_at"]
        ):
            result["simulated_code"] = self.cipher().decrypt(row["code_cipher"].encode()).decode()
        return result

    def prepare_sms(
        self, draft_id: str, key: str, consent: bool, request_id: str
    ) -> tuple[dict[str, Any], tuple[str, str, str] | None]:
        self.scope()
        self.cipher()
        payload = draft_id + "|" + str(consent)
        replay = self.replay("sms", key, payload)
        if replay:
            return self.verification_view(self.challenge(replay["verification_id"])), None
        if not consent:
            raise DomainError("sms_consent_required", 422)
        draft = self.draft(draft_id)
        self.active(draft)
        phone = self.decrypt(draft["snapshot_cipher"])["phone"]
        phone_hash = draft["phone_hash"]
        self.repo.execute("SELECT pg_advisory_xact_lock(%s)", (int(phone_hash[:15], 16),))
        if self.repo.one(
            "SELECT id FROM contact_verification WHERE phone_hash=%s AND delivery_sta"
            "te='unknown' AND verified_at IS NULL AND expires_at>now()",
            (phone_hash,),
        ):
            raise DomainError("verification_delivery_unknown", 409)
        recent = self.repo.one(
            "SELECT count(*) AS n,max(created_at) AS latest FROM contact_verification"
            " WHERE (phone_hash=%s OR visitor_id=%s) AND created_at>now()-interval '1"
            "5 minutes'",
            (phone_hash, self.actor.id),
        )
        if recent and (
            recent["n"] >= 3
            or (recent["latest"] and recent["latest"] > now() - timedelta(seconds=60))
        ):
            raise DomainError("verification_rate_limited", 429)
        verification_id, code = str(uuid4()), f"{secrets.randbelow(1000000):06d}"
        a = self.actor
        self.repo.execute(
            "INSERT INTO contact_verification(id,tenant_id,store_id,visitor_id,draft_id,"
            "request_key,phone_hash,code_hash,code_cipher,delivery_state,simulated,"
            "sms_consent_at,sms_consent_method,consent_request_id,expires_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'unknown',%s,now(),'customer_button',%s,%s)",
            (
                verification_id,
                a.tenant_id,
                a.store_id,
                a.id,
                draft_id,
                key,
                phone_hash,
                self.hashed(verification_id + ":" + code),
                self.cipher().encrypt(code.encode()).decode(),
                self.settings.booking_sms_provider == "simulated",
                request_id,
                now() + timedelta(minutes=5),
            ),
        )
        self.record("sms", key, payload, {"verification_id": verification_id})
        self.repo.audit(a, "appointment.verification_request", verification_id, request_id)
        return self.verification_view(self.challenge(verification_id)), (
            phone,
            code,
            verification_id,
        )

    def verify(self, verification_id: str, code: str, request_id: str) -> dict[str, Any]:
        self.scope()
        row = self.challenge(verification_id)
        self.active(self.draft(str(row["draft_id"])))
        if row["verified_at"] and row["verified_until"] > now() and not row["consumed_at"]:
            return self.verification_view(row)
        if (
            row["expires_at"] <= now()
            or row["consumed_at"]
            or row["attempts"] >= 5
            or row["delivery_state"] == "rejected"
        ):
            return {"error": "verification_expired_or_locked"}
        self.repo.execute(
            "UPDATE contact_verification SET attempts=attempts+1 WHERE id=%s", (verification_id,)
        )
        if not hmac.compare_digest(row["code_hash"], self.hashed(verification_id + ":" + code)):
            self.repo.audit(
                self.actor, "appointment.verification_denied", verification_id, request_id
            )
            return {"error": "verification_code_invalid"}
        self.repo.execute(
            "UPDATE contact_verification SET verified_at=now(),verified_until=now()+i"
            "nterval '15 minutes' WHERE id=%s",
            (verification_id,),
        )
        self.repo.audit(self.actor, "appointment.contact_verified", verification_id, request_id)
        return self.verification_view(self.challenge(verification_id))

    def appointment_view(self, row: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.decrypt(row["snapshot_cipher"])
        return {
            "id": str(row["id"]),
            "request_key": str(row["request_key"]),
            "state": row["state"],
            "version": row["version"],
            "confirmed_at": row["confirmed_at"].isoformat() if row["confirmed_at"] else None,
            "decision_reason": row["decision_reason"],
            "arrived_at": row["arrived_at"].isoformat() if row["arrived_at"] else None,
            "change_proposal": current_proposal(self.repo, row),
            "simulated": row["simulated"],
            "created_at": row["created_at"].isoformat(),
            "name": snapshot["name"],
            "phone_masked": snapshot["phone"][:3] + "****" + snapshot["phone"][-4:],
            "desired_at": snapshot["desired_at"],
            "intention": snapshot["intention"],
            "project_title": snapshot["project_title"],
            "store_name": snapshot["store_name"],
        }

    def appointments(self) -> list[dict[str, Any]]:
        a = self.actor
        return [
            self.appointment_view(row)
            for row in self.repo.all(
                "SELECT a.*,c.snapshot_cipher,c.request_key FROM appointment a "
                "JOIN appointment_confirmation c ON c.id=a.confirmation_id "
                "WHERE a.thread_id=%s AND a.tenant_id=%s AND a.store_id=%s AND a.visitor_id=%s "
                "ORDER BY a.created_at DESC LIMIT 20",
                (self.thread, a.tenant_id, a.store_id, a.id),
            )
        ]

    def confirm(self, draft_id: str, data: ConfirmInput, request_id: str) -> dict[str, Any]:
        self.scope()
        self.cipher()
        payload = draft_id + "|" + data.model_dump_json()
        replay = self.replay("confirm", str(data.request_key), payload)
        if replay:
            a = self.actor
            stored = self.repo.one(
                "SELECT a.*,c.snapshot_cipher,c.request_key FROM appointment a "
                "JOIN appointment_confirmation c ON c.id=a.confirmation_id "
                "WHERE a.id=%s AND a.thread_id=%s AND a.tenant_id=%s "
                "AND a.store_id=%s AND a.visitor_id=%s",
                (replay["appointment_id"], self.thread, a.tenant_id, a.store_id, a.id),
            )
            row = self.appointment_view(stored) if stored else None
            if not row:
                raise DomainError("appointment_not_found", 404)
            return row
        if not data.accepted or data.confirmation_text != CONFIRMATION_TEXT:
            raise DomainError("customer_confirmation_required", 422)
        draft = self.draft(draft_id)
        self.active(draft)
        if not hmac.compare_digest(draft["snapshot_hash"], data.snapshot_hash):
            raise DomainError("draft_snapshot_changed", 409)
        receipt = self.challenge(str(data.verification_id))
        if (
            str(receipt["draft_id"]) != draft_id
            or receipt["phone_hash"] != draft["phone_hash"]
            or not receipt["verified_at"]
            or receipt["verified_until"] <= now()
            or receipt["consumed_at"]
        ):
            raise DomainError("contact_verification_required", 409)
        if receipt["simulated"] and (
            self.settings.environment == "production" or not self.settings.allow_simulated_data
        ):
            raise DomainError("simulated_verification_denied", 403)
        appointment_id, confirmation_id = str(uuid4()), str(uuid4())
        a = self.actor
        self.repo.execute(
            "INSERT INTO appointment_confirmation(id,tenant_id,store_id,visitor_id,draft_id,"
            "verification_id,request_key,snapshot_hash,snapshot_cipher,confirmation_text,"
            "method,evidence_request_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'customer_button',%s)",
            (
                confirmation_id,
                a.tenant_id,
                a.store_id,
                a.id,
                draft_id,
                data.verification_id,
                data.request_key,
                draft["snapshot_hash"],
                draft["snapshot_cipher"],
                CONFIRMATION_TEXT,
                request_id,
            ),
        )
        self.repo.execute(
            "INSERT INTO appointment(id,tenant_id,store_id,visitor_id,thread_id,confi"
            "rmation_id,state,simulated) VALUES(%s,%s,%s,%s,%s,%s,'pending_store_conf"
            "irmation',%s)",
            (
                appointment_id,
                a.tenant_id,
                a.store_id,
                a.id,
                self.thread,
                confirmation_id,
                draft["simulated"] or receipt["simulated"],
            ),
        )
        self.repo.execute(
            "INSERT INTO appointment_event(tenant_id,store_id,visitor_id,appointment_id,"
            "event,actor_id) VALUES(%s,%s,%s,%s,'submitted',%s)",
            (a.tenant_id, a.store_id, a.id, appointment_id, a.id),
        )
        self.repo.execute(
            "INSERT INTO booking_outbox(tenant_id,store_id,visitor_id,appointment_id,topic) "
            "VALUES(%s,%s,%s,%s,'appointment.submitted')",
            (a.tenant_id, a.store_id, a.id, appointment_id),
        )
        self.repo.execute(
            "UPDATE appointment_draft SET status='submitted' WHERE id=%s", (draft_id,)
        )
        self.repo.execute(
            "UPDATE contact_verification SET consumed_at=now() WHERE id=%s", (data.verification_id,)
        )
        self.record("confirm", str(data.request_key), payload, {"appointment_id": appointment_id})
        self.repo.audit(a, "appointment.submit", appointment_id, request_id)
        return self.appointments()[0]

    def state(self) -> dict[str, Any]:
        self.scope()
        trigger = self.eligible_run()
        if trigger and self.repo.one(
            "SELECT id FROM appointment_draft WHERE trigger_run_id=%s AND status='submitted'",
            (trigger,),
        ):
            trigger = None
        if not self.configured():
            return {
                "configured": False,
                "trigger_run_id": trigger,
                "draft": None,
                "verification": None,
                "appointments": [],
                "blocked_reason": "verification_not_configured",
            }
        draft = self.repo.one(
            "SELECT * FROM appointment_draft WHERE thread_id=%s AND status='active' O"
            "RDER BY created_at DESC LIMIT 1 FOR UPDATE",
            (self.thread,),
        )
        reason = ""
        if draft:
            try:
                self.active(draft)
            except DomainError as error:
                reason = error.code
        verification = (
            self.repo.one(
                "SELECT * FROM contact_verification WHERE draft_id=%s ORDER BY created_at"
                " DESC LIMIT 1",
                (draft["id"],),
            )
            if draft
            else None
        )
        return {
            "configured": True,
            "simulated_verification": self.settings.booking_sms_provider == "simulated",
            "trigger_run_id": trigger,
            "draft": self.draft_view(draft) if draft else None,
            "verification": self.verification_view(verification) if verification else None,
            "appointments": self.appointments(),
            "blocked_reason": reason,
        }

    def discard(self, draft_id: str, request_id: str) -> dict[str, bool]:
        self.scope()
        draft = self.draft(draft_id)
        if draft["status"] == "submitted":
            raise DomainError("draft_already_submitted", 409)
        self.repo.execute(
            "UPDATE appointment_draft SET status='discarded' WHERE id=%s", (draft_id,)
        )
        self.repo.audit(self.actor, "appointment.draft_discard", draft_id, request_id)
        return {"discarded": True}


class BookingApplication:
    """Network delivery starts only after a persistent unknown receipt has committed."""

    def __init__(self, settings: Settings, gateway: SmsGateway | None = None) -> None:
        self.settings, self.gateway = settings, gateway

    def send_code(
        self, actor: Actor, thread: str, draft_id: str, key: str, consent: bool, request_id: str
    ) -> dict[str, Any]:
        with transaction(self.settings.database_url) as repo:
            service = BookingService(repo, self.settings, actor, thread)
            result, send = service.prepare_sms(draft_id, key, consent, request_id)
        if send is None:
            return result
        try:
            delivery = (self.gateway or sms_gateway(self.settings)).send(*send)
        except Exception:
            delivery = Delivery("unknown")
        with transaction(self.settings.database_url) as repo:
            service = BookingService(repo, self.settings, actor, thread)
            service.scope()
            row = service.challenge(send[2])
            repo.execute(
                "UPDATE contact_verification SET delivery_state=%s,provider_receipt=%s WHERE id=%s",
                (delivery.state, delivery.receipt, row["id"]),
            )
            return service.verification_view(service.challenge(send[2]))
