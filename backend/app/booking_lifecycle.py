"""Customer consent and store actions are scoped, immutable and transactionally replayable."""

import hmac
import json
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.booking import BookingService
from app.booking_projection import current_proposal
from app.config import Settings
from app.domain import Actor, DomainError, Repository, now
from app.staff_booking import StaffBookingService

CANCEL_TEXT = "确认取消本次预约"
ACCEPT_CHANGE_TEXT = "确认接受新的到店时间"
REJECT_CHANGE_TEXT = "保留原安排，拒绝此次改约"


class ActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    expected_version: int = Field(ge=1)
    accepted: bool


class ProposeInput(ActionInput):
    proposed_at: AwareDatetime
    availability_checked: bool


class RespondInput(ActionInput):
    proposal_id: UUID
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["accept", "reject"]
    confirmation_text: str = Field(max_length=100)


class CancelInput(ActionInput):
    confirmation_text: str = Field(max_length=100)


class ArriveInput(ActionInput):
    identity_checked: bool


class BookingLifecycle:
    def __init__(
        self,
        repo: Repository,
        settings: Settings,
        actor: Actor,
        store: str,
        thread: str | None = None,
    ) -> None:
        self.repo, self.settings, self.actor, self.store, self.thread = (
            repo,
            settings,
            actor,
            store,
            thread,
        )
        scoped = Actor(actor.id, actor.tenant_id, store, actor.kind, actor.session_id)
        self.booking = BookingService(repo, settings, scoped, thread or "")
        self.staff = StaffBookingService(repo, settings, actor, store)

    def scope(self, kind: str) -> None:
        if self.actor.kind != kind:
            raise DomainError("unauthenticated", 401)
        if kind == "visitor":
            self.booking.scope()
        else:
            self.staff.grant("appointment_read")
            self.staff.grant("appointment_manage")

    def row(self, appointment: str) -> dict[str, Any]:
        row = self.repo.one(
            "SELECT a.*,c.snapshot_cipher,c.snapshot_hash,c.request_key,c.draft_id "
            "FROM appointment a JOIN appointment_confirmation c "
            "ON (c.tenant_id,c.store_id,c.visitor_id,c.id)="
            "(a.tenant_id,a.store_id,a.visitor_id,a.confirmation_id) "
            "WHERE a.id=%s AND a.tenant_id=%s AND a.store_id=%s "
            "AND (%s OR NOT a.simulated) "
            "AND (%s::uuid IS NULL OR (a.visitor_id=%s AND a.thread_id=%s)) FOR UPDATE OF a",
            (
                appointment,
                self.actor.tenant_id,
                self.store,
                self.settings.allow_simulated_data,
                self.thread,
                self.actor.id,
                self.thread,
            ),
        )
        if not row:
            raise DomainError("appointment_not_found", 404)
        return row

    def result(self, row: dict[str, Any], request: str) -> dict[str, Any]:
        if self.actor.kind == "staff":
            return self.staff.detail(str(row["id"]), request)
        return self.booking.appointment_view(row)

    def start(
        self, kind: str, operation: str, appointment: str, data: ActionInput, request: str
    ) -> tuple[dict[str, Any], str, bool]:
        self.scope(kind)
        key = str(data.request_key)
        payload = json.dumps(
            {
                "operation": operation,
                "appointment": appointment,
                "store": self.store,
                "thread": self.thread,
                **data.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        self.repo.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"{kind}-booking/{self.actor.tenant_id}/{self.actor.id}/{key}",),
        )
        row = self.row(appointment)
        if kind == "staff":
            replay = self.repo.one(
                "SELECT request_hash FROM staff_booking_idempotency WHERE tenant_id=%s "
                "AND staff_id=%s AND request_key=%s",
                (self.actor.tenant_id, self.actor.id, key),
            )
            if replay and not hmac.compare_digest(
                replay["request_hash"], self.booking.hashed(payload)
            ):
                raise DomainError("booking_key_conflict", 409)
        else:
            replay = self.booking.replay("lifecycle", key, payload)
        if replay:
            return row, payload, True
        if not data.accepted:
            raise DomainError("customer_confirmation_required", 422)
        if row["version"] != data.expected_version:
            raise DomainError("appointment_state_conflict", 409)
        return row, payload, False

    def valid_time(self, value: datetime) -> None:
        if not now() + timedelta(minutes=15) <= value <= now() + timedelta(days=90):
            raise DomainError("appointment_time_invalid", 409)

    def evidence(self, snapshot: dict[str, Any]) -> None:
        if self.booking.policy()["id"] != snapshot["policy"]["id"]:
            raise DomainError("booking_policy_changed", 409)
        self.booking.project(snapshot["project_version_id"])

    def finish(
        self,
        row: dict[str, Any],
        data: ActionInput,
        operation: str,
        payload: str,
        snapshot: dict[str, Any],
        text: str,
        request: str,
    ) -> dict[str, Any]:
        a = self.actor
        raw = json.dumps(
            {
                "appointment_id": str(row["id"]),
                "version": row["version"] + 1,
                "operation": operation,
                "snapshot": snapshot,
                "input": data.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        self.repo.execute(
            "INSERT INTO booking_action_confirmation(id,tenant_id,store_id,visitor_id,"
            "appointment_id,actor_id,operation,snapshot_hash,snapshot_cipher,confirmation_text,"
            "method,evidence_request_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                str(uuid4()),
                a.tenant_id,
                self.store,
                row["visitor_id"],
                row["id"],
                a.id,
                operation,
                self.booking.hashed(raw),
                self.booking.cipher().encrypt(raw.encode()).decode(),
                text,
                "customer_button" if a.kind == "visitor" else "staff_button",
                request,
            ),
        )
        self.repo.execute(
            "UPDATE appointment SET version=version+1,updated_at=now() "
            "WHERE id=%s AND tenant_id=%s AND store_id=%s",
            (row["id"], a.tenant_id, self.store),
        )
        self.repo.execute(
            "INSERT INTO appointment_event(tenant_id,store_id,visitor_id,appointment_id,"
            "event,actor_id,version,request_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                a.tenant_id,
                self.store,
                row["visitor_id"],
                row["id"],
                operation,
                a.id,
                row["version"] + 1,
                request,
            ),
        )
        if a.kind == "staff":
            self.repo.execute(
                "INSERT INTO staff_booking_idempotency(tenant_id,store_id,staff_id,request_key,"
                "request_hash,appointment_id,visitor_id) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    a.tenant_id,
                    self.store,
                    a.id,
                    str(data.request_key),
                    self.booking.hashed(payload),
                    row["id"],
                    row["visitor_id"],
                ),
            )
        else:
            self.booking.record(
                "lifecycle", str(data.request_key), payload, {"appointment_id": str(row["id"])}
            )
        self.repo.audit(a, "appointment." + operation, str(row["id"]), request)
        return self.result(self.row(str(row["id"])), request)

    def propose(self, appointment: str, data: ProposeInput, request: str) -> dict[str, Any]:
        row, payload, replay = self.start("staff", "change_proposed", appointment, data, request)
        if replay:
            return self.result(row, request)
        if row["state"] not in ("pending_store_confirmation", "confirmed"):
            raise DomainError("appointment_state_conflict", 409)
        if not data.availability_checked:
            raise DomainError("store_confirmation_required", 422)
        self.valid_time(data.proposed_at)
        snapshot = self.booking.decrypt(row["snapshot_cipher"])
        self.evidence(snapshot)
        previous_time = row["confirmed_at"] or datetime.fromisoformat(snapshot["desired_at"])
        if previous_time == data.proposed_at:
            raise DomainError("appointment_time_unchanged", 422)
        snapshot = {
            **snapshot,
            "proposed_at": data.proposed_at.isoformat(),
            "previous_time": previous_time.isoformat(),
            "original_state": row["state"],
        }
        raw = json.dumps(snapshot, sort_keys=True)
        self.repo.execute(
            "UPDATE booking_change_proposal SET status='superseded' "
            "WHERE appointment_id=%s AND status='active'",
            (appointment,),
        )
        self.repo.execute(
            "INSERT INTO booking_change_proposal(id,tenant_id,store_id,visitor_id,appointment_id,"
            "staff_id,proposed_version,snapshot_cipher,snapshot_hash,"
            "proposed_at,status,expires_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s)",
            (
                str(uuid4()),
                self.actor.tenant_id,
                self.store,
                row["visitor_id"],
                appointment,
                self.actor.id,
                row["version"] + 1,
                self.booking.cipher().encrypt(raw.encode()).decode(),
                self.booking.hashed(raw),
                data.proposed_at,
                now() + timedelta(minutes=30),
            ),
        )
        return self.finish(
            row, data, "change_proposed", payload, snapshot, "提出新时间，等待客户确认", request
        )

    def respond(self, appointment: str, data: RespondInput, request: str) -> dict[str, Any]:
        operation = "change_accepted" if data.decision == "accept" else "change_rejected"
        row, payload, replay = self.start("visitor", operation, appointment, data, request)
        if replay:
            return self.result(row, request)
        text = ACCEPT_CHANGE_TEXT if data.decision == "accept" else REJECT_CHANGE_TEXT
        if data.confirmation_text != text:
            raise DomainError("customer_confirmation_required", 422)
        proposal = self.repo.one(
            "SELECT * FROM booking_change_proposal WHERE id=%s AND tenant_id=%s AND store_id=%s "
            "AND visitor_id=%s AND appointment_id=%s FOR UPDATE",
            (data.proposal_id, self.actor.tenant_id, self.store, self.actor.id, appointment),
        )
        if (
            not proposal
            or proposal["status"] != "active"
            or proposal["expires_at"] <= now()
            or proposal["proposed_version"] != row["version"]
            or not hmac.compare_digest(proposal["snapshot_hash"], data.snapshot_hash)
            or row["state"] not in ("pending_store_confirmation", "confirmed")
        ):
            raise DomainError("change_proposal_invalid", 409)
        snapshot = self.booking.decrypt(proposal["snapshot_cipher"])
        if data.decision == "accept":
            self.valid_time(proposal["proposed_at"])
            self.evidence(snapshot)
            # The proposing store employee must still hold read/manage access.
            grants = self.repo.all(
                "SELECT g.permission FROM store_grant g JOIN staff s ON "
                "(s.tenant_id,s.id)=(g.tenant_id,g.staff_id) "
                "WHERE g.tenant_id=%s AND g.store_id=%s "
                "AND g.staff_id=%s AND s.active AND (%s OR NOT s.simulated) FOR SHARE OF g,s",
                (
                    self.actor.tenant_id,
                    self.store,
                    proposal["staff_id"],
                    self.settings.allow_simulated_data,
                ),
            )
            if not {"appointment_read", "appointment_manage"}.issubset(
                {g["permission"] for g in grants}
            ):
                raise DomainError("change_proposer_unavailable", 409)
            self.repo.execute(
                "UPDATE appointment SET state='confirmed',confirmed_at=%s,decision_reason=NULL "
                "WHERE id=%s",
                (proposal["proposed_at"], appointment),
            )
        self.repo.execute(
            "UPDATE booking_change_proposal SET status=%s WHERE id=%s",
            ("accepted" if data.decision == "accept" else "rejected", data.proposal_id),
        )
        return self.finish(row, data, operation, payload, snapshot, text, request)

    def cancel(self, appointment: str, data: CancelInput, request: str) -> dict[str, Any]:
        row, payload, replay = self.start("visitor", "cancelled", appointment, data, request)
        if replay:
            return self.result(row, request)
        if data.confirmation_text != CANCEL_TEXT:
            raise DomainError("customer_confirmation_required", 422)
        if row["state"] not in ("pending_store_confirmation", "confirmed"):
            raise DomainError("appointment_state_conflict", 409)
        snapshot = self.booking.decrypt(row["snapshot_cipher"])
        snapshot["current_confirmed_at"] = (
            row["confirmed_at"].isoformat() if row["confirmed_at"] else None
        )
        self.repo.execute("UPDATE appointment SET state='cancelled' WHERE id=%s", (appointment,))
        self.repo.execute(
            "UPDATE booking_change_proposal SET status='cancelled' "
            "WHERE appointment_id=%s AND status='active'",
            (appointment,),
        )
        return self.finish(row, data, "cancelled", payload, snapshot, CANCEL_TEXT, request)

    def arrive(self, appointment: str, data: ArriveInput, request: str) -> dict[str, Any]:
        row, payload, replay = self.start("staff", "arrived", appointment, data, request)
        if replay:
            return self.result(row, request)
        if not data.identity_checked:
            raise DomainError("arrival_confirmation_required", 422)
        if row["state"] != "confirmed" or current_proposal(self.repo, row):
            raise DomainError("appointment_state_conflict", 409)
        self.repo.execute(
            "UPDATE appointment SET state='arrived',arrived_at=now() WHERE id=%s", (appointment,)
        )
        return self.finish(
            row,
            data,
            "arrived",
            payload,
            self.booking.decrypt(row["snapshot_cipher"]),
            "已核实客户身份及实际到店",
            request,
        )
