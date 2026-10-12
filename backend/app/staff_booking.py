"""Scoped store inbox and explicit decisions; never grants access by staff role alone."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field

from app.booking import BookingService
from app.booking_projection import current_proposal
from app.config import Settings
from app.domain import Actor, DomainError, Repository, now


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    expected_version: int = Field(ge=1)
    action: Literal["confirm", "decline"]
    accepted: bool
    availability_checked: bool = False
    reason: Literal["no_availability", "unable_to_contact", "other"] | None = None


class StaffBookingService:
    def __init__(self, repo: Repository, settings: Settings, actor: Actor, store: str) -> None:
        self.repo, self.settings, self.actor, self.store = repo, settings, actor, store

    def grant(self, permission: str) -> None:
        a = self.actor
        if a.kind != "staff" or not self.repo.one(
            "SELECT a.id FROM auth_session a JOIN staff u "
            "ON (u.tenant_id,u.id)=(a.tenant_id,a.staff_id) "
            "JOIN tenant t ON t.id=a.tenant_id WHERE a.id=%s AND a.staff_id=%s AND a.tenant_id=%s "
            "AND a.revoked_at IS NULL AND a.expires_at>now() AND u.active "
            "AND (%s OR NOT(u.simulated OR t.simulated)) FOR UPDATE OF a FOR SHARE OF u,t",
            (a.session_id, a.id, a.tenant_id, self.settings.allow_simulated_data),
        ):
            raise DomainError("unauthenticated", 401)
        if not self.repo.one(
            "SELECT g.staff_id FROM store_grant g JOIN store s "
            "ON (s.tenant_id,s.id)=(g.tenant_id,g.store_id) "
            "WHERE g.tenant_id=%s AND g.staff_id=%s AND g.store_id=%s AND g.permission=%s "
            "AND s.active AND (%s OR NOT s.simulated) FOR SHARE OF g,s",
            (a.tenant_id, a.id, self.store, permission, self.settings.allow_simulated_data),
        ):
            raise DomainError("store_permission_denied")

    def row(self, appointment: str, lock: bool = False) -> dict[str, Any]:
        row = self.repo.one(
            "SELECT a.*,c.snapshot_cipher,c.snapshot_hash,c.confirmed_at AS customer_confirmed_at,"
            "c.method,c.evidence_request_id,c.draft_id FROM appointment a "
            "JOIN appointment_confirmation c ON (c.tenant_id,c.store_id,c.visitor_id,c.id)="
            "(a.tenant_id,a.store_id,a.visitor_id,a.confirmation_id) "
            "WHERE a.id=%s AND a.tenant_id=%s AND a.store_id=%s "
            "AND (%s OR NOT a.simulated)" + (" FOR UPDATE OF a" if lock else ""),
            (appointment, self.actor.tenant_id, self.store, self.settings.allow_simulated_data),
        )
        if not row:
            raise DomainError("appointment_not_found", 404)
        return row

    def snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.booking_encryption_key.get_secret_value():
            raise DomainError("verification_not_configured", 503)
        return dict(
            json.loads(
                Fernet(self.settings.booking_encryption_key.get_secret_value().encode()).decrypt(
                    row["snapshot_cipher"].encode()
                )
            )
        )

    def view(self, row: dict[str, Any]) -> dict[str, Any]:
        snapshot = self.snapshot(row)
        return {
            "id": str(row["id"]),
            "version": row["version"],
            "state": row["state"],
            "simulated": row["simulated"],
            "name": snapshot["name"],
            "phone_masked": snapshot["phone"][:3] + "****" + snapshot["phone"][-4:],
            "intention": snapshot["intention"],
            "desired_at": snapshot["desired_at"],
            "project_title": snapshot["project_title"],
            "created_at": row["created_at"],
            "confirmed_at": row["confirmed_at"],
            "decision_reason": row["decision_reason"],
            "arrived_at": row["arrived_at"],
            "change_proposal": current_proposal(self.repo, row),
            "customer_confirmed_at": row["customer_confirmed_at"],
            "confirmation_method": row["method"],
        }

    def inbox(self, state: str | None, limit: int, offset: int, request_id: str) -> dict[str, Any]:
        self.grant("appointment_read")
        params = (
            self.actor.tenant_id,
            self.store,
            self.settings.allow_simulated_data,
            state,
            state,
        )
        where = (
            "tenant_id=%s AND store_id=%s AND (%s OR NOT simulated) "
            "AND (%s::text IS NULL OR state=%s)"
        )
        rows = self.repo.all(
            "SELECT id FROM appointment WHERE "
            + where
            + " ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s",
            (*params, limit, offset),
        )
        total = self.repo.one("SELECT count(*) AS n FROM appointment WHERE " + where, params)
        counts = self.repo.all(
            "SELECT state,count(*) AS n FROM appointment WHERE tenant_id=%s AND store_id=%s "
            "AND (%s OR NOT simulated) GROUP BY state",
            params[:3],
        )
        self.repo.audit(self.actor, "appointment.inbox_read", self.store, request_id)
        return {
            "items": [self.view(self.row(str(row["id"]))) for row in rows],
            "total": total["n"] if total else 0,
            "counts": {row["state"]: row["n"] for row in counts},
        }

    def detail(self, appointment: str, request_id: str) -> dict[str, Any]:
        self.grant("appointment_read")
        row = self.row(appointment)
        events = self.repo.all(
            "SELECT event,occurred_at,version,reason FROM appointment_event "
            "WHERE tenant_id=%s AND store_id=%s AND visitor_id=%s "
            "AND appointment_id=%s ORDER BY id",
            (self.actor.tenant_id, self.store, row["visitor_id"], appointment),
        )
        self.repo.audit(self.actor, "appointment.detail_read", appointment, request_id)
        return {**self.view(row), "events": events}

    def contact(self, appointment: str, request_id: str) -> dict[str, str]:
        self.grant("appointment_read")
        self.grant("appointment_contact")
        row = self.row(appointment)
        self.repo.audit(self.actor, "appointment.contact_read", appointment, request_id)
        return {"phone": str(self.snapshot(row)["phone"])}

    def decide(self, appointment: str, data: DecisionInput, request_id: str) -> dict[str, Any]:
        self.grant("appointment_read")
        self.grant("appointment_manage")
        # Serialize keys across appointments before taking the resource lock.
        a = self.actor
        key = str(data.request_key)
        self.repo.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"staff-booking/{a.tenant_id}/{a.id}/{key}",),
        )
        payload = json.dumps(
            {"store": self.store, "appointment": appointment, **data.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        )
        hashed = hmac.new(
            self.settings.booking_hmac_key.get_secret_value().encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        replay = self.repo.one(
            "SELECT request_hash FROM staff_booking_idempotency WHERE tenant_id=%s "
            "AND staff_id=%s AND request_key=%s",
            (a.tenant_id, a.id, key),
        )
        row = self.row(appointment, lock=True)
        if replay:
            if not hmac.compare_digest(replay["request_hash"], hashed):
                raise DomainError("booking_key_conflict", 409)
            return self.detail(appointment, request_id)
        if (
            not data.accepted
            or (data.action == "confirm" and (not data.availability_checked or data.reason))
            or (data.action == "decline" and not data.reason)
        ):
            raise DomainError("store_confirmation_required", 422)
        if row["version"] != data.expected_version or row["state"] != "pending_store_confirmation":
            raise DomainError("appointment_state_conflict", 409)
        if current_proposal(self.repo, row):
            raise DomainError("appointment_state_conflict", 409)
        confirmed = None
        if data.action == "confirm":
            snapshot = self.snapshot(row)
            # Changing the customer's accepted time requires new customer consent.
            confirmed = datetime.fromisoformat(snapshot["desired_at"])
            if not now() + timedelta(minutes=15) <= confirmed <= now() + timedelta(days=90):
                raise DomainError("appointment_time_invalid", 409)
            evidence_actor = Actor(a.id, a.tenant_id, self.store, a.kind, a.session_id)
            evidence = BookingService(
                self.repo, self.settings, evidence_actor, str(row["thread_id"])
            )
            if evidence.policy()["id"] != snapshot["policy"]["id"]:
                raise DomainError("booking_policy_changed", 409)
            draft = self.repo.one(
                "SELECT project_version_id FROM appointment_draft WHERE id=%s", (row["draft_id"],)
            )
            evidence.project(
                str(draft["project_version_id"]) if draft and draft["project_version_id"] else None
            )
        state = "confirmed" if data.action == "confirm" else "declined"
        self.repo.execute(
            "UPDATE appointment SET state=%s,version=version+1,confirmed_at=%s,"
            "decision_reason=%s,updated_at=now() "
            "WHERE id=%s AND tenant_id=%s AND store_id=%s",
            (state, confirmed, data.reason, appointment, a.tenant_id, self.store),
        )
        self.repo.execute(
            "INSERT INTO appointment_event(tenant_id,store_id,visitor_id,appointment_id,"
            "event,actor_id,version,request_id,reason) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                a.tenant_id,
                self.store,
                row["visitor_id"],
                appointment,
                state,
                a.id,
                row["version"] + 1,
                request_id,
                data.reason,
            ),
        )
        self.repo.execute(
            "INSERT INTO staff_booking_idempotency(tenant_id,store_id,staff_id,request_key,"
            "request_hash,appointment_id,visitor_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (a.tenant_id, self.store, a.id, key, hashed, appointment, row["visitor_id"]),
        )
        self.repo.audit(a, "appointment." + state, appointment, request_id)
        return self.detail(appointment, request_id)
