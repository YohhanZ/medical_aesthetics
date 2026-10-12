"""Append-only visit intentions with scoped, personal customer confirmation. No model tools."""

import hmac
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.booking import BookingService
from app.config import Settings
from app.domain import Actor, DomainError, Repository
from app.services import KnowledgeService
from app.staff_booking import StaffBookingService

ACCEPT_TEXT = "确认本次咨询意向（不代表治疗或合同同意）"
REJECT_TEXT = "暂不确认，继续沟通"


class CommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    accepted: bool


class CaseCreate(CommandInput):
    appointment_id: UUID
    expected_appointment_version: int = Field(ge=1)


class CaseRevision(CommandInput):
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=40)
    intention: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=300)
    project_version_id: UUID | None = None


class CaseDecision(CommandInput):
    expected_version: int = Field(ge=1)
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["accept", "reject"]
    confirmation_text: str = Field(max_length=100)


class ConsultationCases:
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

    def scope(self, write: bool = False) -> None:
        if self.actor.kind == "visitor":
            self.booking.scope()
        else:
            self.staff.grant("customer_read")
            if write:
                self.staff.grant("customer_manage")

    def appointment(self, id: str) -> dict[str, Any]:
        row = self.repo.one(
            "SELECT a.*,c.snapshot_cipher FROM appointment a JOIN appointment_confirmation c "
            "ON (c.tenant_id,c.store_id,c.visitor_id,c.id)="
            "(a.tenant_id,a.store_id,a.visitor_id,a.confirmation_id) "
            "WHERE a.id=%s AND a.tenant_id=%s AND a.store_id=%s AND (%s OR NOT a.simulated) "
            "AND (%s::uuid IS NULL OR (a.visitor_id=%s AND a.thread_id=%s)) FOR UPDATE OF a",
            (
                id,
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

    def row(self, id: str) -> dict[str, Any]:
        row = self.repo.one(
            "SELECT c.* FROM consultation_case c JOIN appointment a ON "
            "(a.tenant_id,a.store_id,a.visitor_id,a.id)="
            "(c.tenant_id,c.store_id,c.visitor_id,c.appointment_id) "
            "WHERE c.id=%s AND c.tenant_id=%s AND c.store_id=%s AND (%s OR NOT c.simulated) "
            "AND (%s::uuid IS NULL OR (c.visitor_id=%s AND a.thread_id=%s)) FOR UPDATE OF c",
            (
                id,
                self.actor.tenant_id,
                self.store,
                self.settings.allow_simulated_data,
                self.thread,
                self.actor.id,
                self.thread,
            ),
        )
        if not row:
            raise DomainError("consultation_not_found", 404)
        return row

    def revisions(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        return self.repo.all(
            "SELECT r.*,d.decision,d.confirmed_at FROM consultation_revision r "
            "LEFT JOIN consultation_decision d "
            "USING(tenant_id,store_id,visitor_id,case_id,version) "
            "WHERE r.tenant_id=%s AND r.store_id=%s AND r.visitor_id=%s AND r.case_id=%s "
            "ORDER BY r.version",
            (row["tenant_id"], self.store, row["visitor_id"], row["id"]),
        )

    def options(self, request: str) -> dict[str, Any]:
        self.scope()
        actor = Actor(
            self.actor.id, self.actor.tenant_id, self.store, self.actor.kind, self.actor.session_id
        )
        rows = KnowledgeService(self.repo, self.settings).evidence(actor)
        self.repo.audit(self.actor, "consultation.options_read", self.store, request)
        return {
            "items": [
                {"id": str(r["id"]), "title": r["title"], "simulated": r["simulated"]}
                for r in rows
                if r["knowledge_key"].startswith("catalog-")
            ]
        }

    def view(self, row: dict[str, Any]) -> dict[str, Any]:
        initial = self.booking.decrypt(row["initial_cipher"])
        versions = [
            {
                **self.booking.decrypt(r["snapshot_cipher"]),
                "version": r["version"],
                "snapshot_hash": r["snapshot_hash"],
                "recorded_at": r["created_at"],
                "decision": r["decision"],
                "confirmed_at": r["confirmed_at"],
            }
            for r in self.revisions(row)
        ]
        return {
            "id": str(row["id"]),
            "appointment_id": str(row["appointment_id"]),
            "version": row["version"],
            "simulated": row["simulated"],
            "initial": {k: initial[k] for k in ("name", "intention", "project_title")},
            "phone_masked": initial["phone"][:3] + "****" + initial["phone"][-4:],
            "current": versions[-1],
            "history": versions,
        }

    def inbox(self, limit: int, offset: int, request: str) -> dict[str, Any]:
        self.scope()
        where = "tenant_id=%s AND store_id=%s AND (%s OR NOT simulated)"
        params = (self.actor.tenant_id, self.store, self.settings.allow_simulated_data)
        rows = self.repo.all(
            "SELECT id FROM consultation_case WHERE "
            + where
            + " ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s",
            (*params, limit, offset),
        )
        total = self.repo.one("SELECT count(*) AS n FROM consultation_case WHERE " + where, params)
        self.repo.audit(self.actor, "consultation.inbox_read", self.store, request)
        return {
            "items": [self.view(self.row(str(r["id"]))) for r in rows],
            "total": total["n"] if total else 0,
        }

    def detail(self, id: str, request: str) -> dict[str, Any]:
        self.scope()
        row = self.row(id)
        self.repo.audit(self.actor, "consultation.detail_read", id, request)
        return self.view(row)

    def customer(self, appointment: str, request: str) -> dict[str, Any] | None:
        self.scope()
        row = self.repo.one(
            "SELECT id FROM consultation_case WHERE appointment_id=%s", (appointment,)
        )
        if not row:
            self.appointment(appointment)
            return None
        return self.detail(str(row["id"]), request)

    def command(self, operation: str, data: CommandInput, resource: str) -> tuple[str, str | None]:
        self.scope(True)
        payload = json.dumps(
            {
                "operation": operation,
                "resource": resource,
                "store": self.store,
                "thread": self.thread,
                **data.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        self.repo.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"consultation/{self.actor.tenant_id}/{self.actor.id}/{data.request_key}",),
        )
        replay = self.repo.one(
            "SELECT request_hash,case_id FROM consultation_command "
            "WHERE tenant_id=%s AND actor_id=%s AND request_key=%s",
            (self.actor.tenant_id, self.actor.id, data.request_key),
        )
        if replay:
            if not hmac.compare_digest(replay["request_hash"], self.booking.hashed(payload)):
                raise DomainError("consultation_key_conflict", 409)
            return payload, str(replay["case_id"])
        if not data.accepted:
            raise DomainError("customer_confirmation_required", 422)
        return payload, None

    def finish(
        self, row: dict[str, Any], data: CommandInput, payload: str, operation: str, request: str
    ) -> dict[str, Any]:
        self.repo.execute(
            "INSERT INTO consultation_command(tenant_id,store_id,visitor_id,"
            "case_id,actor_id,request_key,request_hash) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                self.actor.tenant_id,
                self.store,
                row["visitor_id"],
                row["id"],
                self.actor.id,
                data.request_key,
                self.booking.hashed(payload),
            ),
        )
        self.repo.audit(self.actor, "consultation." + operation, str(row["id"]), request)
        return self.view(self.row(str(row["id"])))

    def revision(self, row: dict[str, Any], snapshot: dict[str, Any]) -> None:
        raw = json.dumps(snapshot, sort_keys=True)
        self.repo.execute(
            "INSERT INTO consultation_revision(tenant_id,store_id,visitor_id,case_id,"
            "version,actor_id,snapshot_cipher,snapshot_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.actor.tenant_id,
                self.store,
                row["visitor_id"],
                row["id"],
                row["version"],
                self.actor.id,
                self.booking.cipher().encrypt(raw.encode()).decode(),
                self.booking.hashed(raw),
            ),
        )

    def create(self, data: CaseCreate, request: str) -> dict[str, Any]:
        if self.actor.kind != "staff":
            raise DomainError("unauthenticated", 401)
        payload, replay = self.command("create", data, str(data.appointment_id))
        if replay:
            return self.detail(replay, request)
        self.staff.grant("appointment_read")
        appointment = self.appointment(str(data.appointment_id))
        if (
            appointment["state"] != "arrived"
            or appointment["version"] != data.expected_appointment_version
        ):
            raise DomainError("appointment_state_conflict", 409)
        existing = self.repo.one(
            "SELECT id FROM consultation_case WHERE appointment_id=%s", (data.appointment_id,)
        )
        if existing:
            raise DomainError("consultation_already_exists", 409)
        self.repo.execute(
            "INSERT INTO consultation_case(id,tenant_id,store_id,visitor_id,appointment_id,"
            "version,initial_cipher,simulated) VALUES(%s,%s,%s,%s,%s,1,%s,%s)",
            (
                id := str(uuid4()),
                self.actor.tenant_id,
                self.store,
                appointment["visitor_id"],
                data.appointment_id,
                appointment["snapshot_cipher"],
                appointment["simulated"],
            ),
        )
        row = self.row(id)
        initial = self.booking.decrypt(row["initial_cipher"])
        self.revision(
            row,
            {k: initial[k] for k in ("name", "intention", "project_version_id", "project_title")}
            | {"reason": "原预约申请，等待到店咨询核实", "source": "original_application"},
        )
        return self.finish(row, data, payload, "create", request)

    def update(self, id: str, data: CaseRevision, request: str) -> dict[str, Any]:
        if self.actor.kind != "staff":
            raise DomainError("unauthenticated", 401)
        payload, replay = self.command("revise", data, id)
        if replay:
            return self.detail(replay, request)
        row = self.row(id)
        appointment = self.appointment(str(row["appointment_id"]))
        if (
            row["version"] != data.expected_version
            or row["version"] >= 200
            or appointment["state"] != "arrived"
        ):
            raise DomainError("consultation_state_conflict", 409)
        if not all(v.strip() for v in (data.name, data.intention, data.reason)):
            raise DomainError("invalid_input", 422)
        project = str(data.project_version_id) if data.project_version_id else None
        title = self.booking.project(project)
        self.repo.execute("UPDATE consultation_case SET version=version+1 WHERE id=%s", (id,))
        row = self.row(id)
        self.revision(
            row,
            {
                "name": data.name.strip(),
                "intention": data.intention.strip(),
                "reason": data.reason.strip(),
                "project_version_id": project,
                "project_title": title,
                "source": "staff_record",
            },
        )
        return self.finish(row, data, payload, "revise", request)

    def decide(self, appointment: str, data: CaseDecision, request: str) -> dict[str, Any]:
        if self.actor.kind != "visitor":
            raise DomainError("unauthenticated", 401)
        payload, replay = self.command("decide", data, appointment)
        if replay:
            return self.detail(replay, request)
        # Same lock ordering as staff revision: case, then its arrival appointment.
        found = self.repo.one(
            "SELECT id FROM consultation_case WHERE appointment_id=%s", (appointment,)
        )
        if not found:
            raise DomainError("consultation_not_found", 404)
        row = self.row(str(found["id"]))
        appt = self.appointment(appointment)
        revision = self.revisions(row)[-1]
        if (
            row["version"] != data.expected_version
            or revision["decision"]
            or appt["state"] != "arrived"
        ):
            raise DomainError("consultation_state_conflict", 409)
        if not hmac.compare_digest(revision["snapshot_hash"], data.snapshot_hash):
            raise DomainError("consultation_snapshot_changed", 409)
        if data.confirmation_text != (ACCEPT_TEXT if data.decision == "accept" else REJECT_TEXT):
            raise DomainError("customer_confirmation_required", 422)
        if data.decision == "accept":
            snapshot = self.booking.decrypt(revision["snapshot_cipher"])
            self.booking.project(snapshot["project_version_id"])
            grants = self.repo.all(
                "SELECT g.permission FROM store_grant g JOIN staff s ON "
                "(s.tenant_id,s.id)=(g.tenant_id,g.staff_id) WHERE g.tenant_id=%s "
                "AND g.store_id=%s AND g.staff_id=%s AND s.active AND (%s OR NOT s.simulated) "
                "FOR SHARE OF g,s",
                (
                    self.actor.tenant_id,
                    self.store,
                    revision["actor_id"],
                    self.settings.allow_simulated_data,
                ),
            )
            if not {"customer_read", "customer_manage"}.issubset({g["permission"] for g in grants}):
                raise DomainError("consultation_author_unavailable", 409)
        self.repo.execute(
            "INSERT INTO consultation_decision(tenant_id,store_id,visitor_id,case_id,version,"
            "decision,snapshot_hash,snapshot_cipher,confirmation_text,method,evidence_request_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'customer_button',%s)",
            (
                self.actor.tenant_id,
                self.store,
                self.actor.id,
                row["id"],
                row["version"],
                data.decision,
                data.snapshot_hash,
                revision["snapshot_cipher"],
                data.confirmation_text,
                request,
            ),
        )
        return self.finish(row, data, payload, "decide", request)
