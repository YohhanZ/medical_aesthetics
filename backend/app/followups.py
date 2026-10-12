"""Store-scoped in-app follow-up invitations; no outbound messaging or model access."""

import hmac
import json
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field

from app.config import Settings
from app.consultation_cases import CommandInput, ConsultationCases
from app.domain import Actor, DomainError, Repository, now

CUSTOMER_TEXT = {
    "accept": "同意本次站内回访计划",
    "reject": "拒绝回访并暂停这份档案的邀请",
    "cancel": "取消回访并暂停这份档案的邀请",
    "feedback": "确认提交本次回访反馈",
    "resume": "恢复这份档案的站内回访邀请",
}


class FollowupCreate(CommandInput):
    case_id: UUID
    expected_case_version: int = Field(ge=1)
    due_at: AwareDatetime
    message: str = Field(min_length=1, max_length=300)


class FollowupStaffAction(CommandInput):
    expected_version: int = Field(ge=1)
    action: Literal["note", "cancel"]
    note: str = Field(min_length=1, max_length=500)


class FollowupResponse(CommandInput):
    expected_version: int = Field(ge=1)
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["accept", "reject", "feedback", "cancel", "resume"]
    confirmation_text: str = Field(max_length=100)
    result: Literal["resolved", "need_help"] | None = None
    feedback: str = Field(default="", max_length=500)


class Followups:
    def __init__(
        self,
        repo: Repository,
        settings: Settings,
        actor: Actor,
        store: str,
        thread: str | None = None,
        appointment: str | None = None,
    ) -> None:
        self.repo, self.settings, self.actor, self.store = repo, settings, actor, store
        self.thread, self.appointment = thread, appointment
        self.cases = ConsultationCases(repo, settings, actor, store, thread)
        self.booking = self.cases.booking

    def scope(self, write: bool = False) -> None:
        self.cases.scope(write)

    def row(self, id: str, lock: bool = False) -> dict[str, Any]:
        row = self.repo.one(
            "SELECT f.*,c.version AS current_case_version,c.initial_cipher,a.thread_id,"
            "r.snapshot_cipher AS source_cipher FROM followup_task f "
            "JOIN consultation_case c ON (c.tenant_id,c.store_id,c.visitor_id,c.id)="
            "(f.tenant_id,f.store_id,f.visitor_id,f.case_id) "
            "JOIN consultation_revision r ON "
            "(r.tenant_id,r.store_id,r.visitor_id,r.case_id,r.version)="
            "(f.tenant_id,f.store_id,f.visitor_id,f.case_id,f.case_version) "
            "JOIN appointment a ON (a.tenant_id,a.store_id,a.visitor_id,a.id)="
            "(c.tenant_id,c.store_id,c.visitor_id,c.appointment_id) "
            "WHERE f.id=%s AND f.tenant_id=%s AND f.store_id=%s AND (%s OR NOT f.simulated) "
            "AND (%s::uuid IS NULL OR (f.visitor_id=%s AND a.thread_id=%s AND a.id=%s))"
            + (" FOR UPDATE OF f" if lock else ""),
            (
                id,
                self.actor.tenant_id,
                self.store,
                self.settings.allow_simulated_data,
                self.thread,
                self.actor.id,
                self.thread,
                self.appointment,
            ),
        )
        if not row:
            raise DomainError("followup_not_found", 404)
        return row

    def view(self, row: dict[str, Any]) -> dict[str, Any]:
        staff = self.actor.kind == "staff"
        events = self.repo.all(
            "SELECT * FROM followup_event WHERE tenant_id=%s AND store_id=%s AND visitor_id=%s "
            "AND case_id=%s AND task_id=%s AND version<=%s "
            "AND (%s OR kind<>'note') ORDER BY version",
            (
                row["tenant_id"],
                self.store,
                row["visitor_id"],
                row["case_id"],
                row["id"],
                row["version"],
                staff,
            ),
        )
        history = []
        for event in events:
            payload = self.booking.decrypt(event["payload_cipher"])
            history.append(
                {
                    "version": event["version"],
                    "kind": event["kind"],
                    "actor_kind": event["actor_kind"],
                    "recorded_at": event["created_at"],
                    "text": payload.get("note", "") if staff else "",
                    "result": payload.get("result"),
                    "feedback": payload.get("feedback", ""),
                    "confirmation_text": payload.get("confirmation_text", ""),
                }
            )
        source = self.booking.decrypt(row["source_cipher"])
        result = {
            "id": str(row["id"]),
            "case_id": str(row["case_id"]),
            "case_version": row["case_version"],
            "source_current": row["case_version"] == row["current_case_version"],
            "version": row["version"],
            "state": row["state"],
            "due_at": row["due_at"],
            "message": self.booking.decrypt(row["plan_cipher"])["message"],
            "snapshot_hash": row["snapshot_hash"],
            "opted_out": row["opted_out"],
            "simulated": row["simulated"],
            "channel": "in_app",
            "history": history,
        }
        if staff:
            initial = self.booking.decrypt(row["initial_cipher"])
            result.update(
                name=source["name"],
                phone_masked=initial["phone"][:3] + "****" + initial["phone"][-4:],
            )
        return result

    def detail(self, id: str, request: str) -> dict[str, Any]:
        self.scope()
        row = self.row(id)
        self.repo.audit(self.actor, "followup.detail_read", id, request)
        return self.view(row)

    def inbox(self, state: str | None, limit: int, offset: int, request: str) -> dict[str, Any]:
        self.scope()
        if self.actor.kind != "staff":
            raise DomainError("unauthenticated", 401)
        where = (
            "tenant_id=%s AND store_id=%s AND (%s OR NOT simulated) "
            "AND (%s::text IS NULL OR state=%s)"
        )
        params = (
            self.actor.tenant_id,
            self.store,
            self.settings.allow_simulated_data,
            state,
            state,
        )
        rows = self.repo.all(
            "SELECT id FROM followup_task WHERE "
            + where
            + " ORDER BY due_at,id LIMIT %s OFFSET %s",
            (*params, limit, offset),
        )
        total = self.repo.one("SELECT count(*) AS n FROM followup_task WHERE " + where, params)
        counts = self.repo.all(
            "SELECT state,count(*) AS n FROM followup_task WHERE tenant_id=%s AND store_id=%s "
            "AND (%s OR NOT simulated) GROUP BY state",
            (self.actor.tenant_id, self.store, self.settings.allow_simulated_data),
        )
        self.repo.audit(self.actor, "followup.inbox_read", self.store, request)
        return {
            "items": [self.view(self.row(str(r["id"]))) for r in rows],
            "total": total["n"] if total else 0,
            "counts": {r["state"]: r["n"] for r in counts},
        }

    def customer(self, request: str) -> dict[str, Any]:
        self.scope()
        self.cases.appointment(str(self.appointment))
        rows = self.repo.all(
            "SELECT f.id FROM followup_task f JOIN consultation_case c ON "
            "(c.tenant_id,c.store_id,c.visitor_id,c.id)="
            "(f.tenant_id,f.store_id,f.visitor_id,f.case_id) "
            "WHERE f.tenant_id=%s AND f.store_id=%s AND f.visitor_id=%s AND c.appointment_id=%s "
            "ORDER BY f.created_at DESC,f.id DESC LIMIT 20",
            (self.actor.tenant_id, self.store, self.actor.id, self.appointment),
        )
        self.repo.audit(self.actor, "followup.customer_read", str(self.appointment), request)
        return {"items": [self.view(self.row(str(r["id"]))) for r in rows]}

    def candidates(self, limit: int, offset: int, request: str) -> dict[str, Any]:
        self.scope()
        where = (
            "c.tenant_id=%s AND c.store_id=%s AND (%s OR NOT c.simulated) AND EXISTS "
            "(SELECT 1 FROM consultation_decision d WHERE "
            "(d.tenant_id,d.store_id,d.visitor_id,d.case_id,d.version)="
            "(c.tenant_id,c.store_id,c.visitor_id,c.id,c.version) AND d.decision='accept')"
        )
        params = (self.actor.tenant_id, self.store, self.settings.allow_simulated_data)
        rows = self.repo.all(
            "SELECT c.* FROM consultation_case c WHERE "
            + where
            + " ORDER BY c.created_at DESC,c.id LIMIT %s OFFSET %s",
            (*params, limit, offset),
        )
        total = self.repo.one(
            "SELECT count(*) AS n FROM consultation_case c WHERE " + where, params
        )
        items = []
        for r in rows:
            initial = self.booking.decrypt(r["initial_cipher"])
            items.append(
                {
                    "id": str(r["id"]),
                    "version": r["version"],
                    "name": initial["name"],
                    "phone_masked": initial["phone"][:3] + "****" + initial["phone"][-4:],
                }
            )
        self.repo.audit(self.actor, "followup.candidates_read", self.store, request)
        return {"items": items, "total": total["n"] if total else 0}

    def command(self, operation: str, data: CommandInput, resource: str) -> tuple[str, str | None]:
        self.scope(True)
        raw = json.dumps(
            {
                "operation": operation,
                "store": self.store,
                "thread": self.thread,
                "appointment": self.appointment,
                "resource": resource,
                **data.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        self.repo.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"followup/{self.actor.tenant_id}/{self.actor.id}/{data.request_key}",),
        )
        previous = self.repo.one(
            "SELECT request_hash,task_id FROM followup_command "
            "WHERE tenant_id=%s AND actor_id=%s AND request_key=%s",
            (self.actor.tenant_id, self.actor.id, data.request_key),
        )
        if previous:
            if not hmac.compare_digest(previous["request_hash"], self.booking.hashed(raw)):
                raise DomainError("followup_key_conflict", 409)
            return raw, str(previous["task_id"])
        if not data.accepted:
            raise DomainError("customer_confirmation_required", 422)
        return raw, None

    def finish(
        self, row: dict[str, Any], data: CommandInput, raw: str, kind: str, request: str
    ) -> dict[str, Any]:
        payload = json.dumps(data.model_dump(mode="json"), sort_keys=True)
        self.repo.execute(
            "INSERT INTO followup_event(tenant_id,store_id,visitor_id,case_id,task_id,version,"
            "actor_id,actor_kind,kind,method,payload_cipher,payload_hash,evidence_request_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                row["tenant_id"],
                self.store,
                row["visitor_id"],
                row["case_id"],
                row["id"],
                row["version"],
                self.actor.id,
                self.actor.kind,
                kind,
                "staff_button" if self.actor.kind == "staff" else "customer_button",
                self.booking.cipher().encrypt(payload.encode()).decode(),
                self.booking.hashed(payload),
                request,
            ),
        )
        self.repo.execute(
            "INSERT INTO followup_command(tenant_id,store_id,visitor_id,case_id,task_id,"
            "actor_id,request_key,request_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                row["tenant_id"],
                self.store,
                row["visitor_id"],
                row["case_id"],
                row["id"],
                self.actor.id,
                data.request_key,
                self.booking.hashed(raw),
            ),
        )
        self.repo.audit(self.actor, "followup." + kind, str(row["id"]), request)
        return self.view(row)

    def create(self, data: FollowupCreate, request: str) -> dict[str, Any]:
        if self.actor.kind != "staff":
            raise DomainError("unauthenticated", 401)
        raw, replay = self.command("create", data, str(data.case_id))
        if replay:
            return self.detail(replay, request)
        case = self.cases.row(str(data.case_id))
        current = self.cases.revisions(case)[-1]
        if case["version"] != data.expected_case_version or current["decision"] != "accept":
            raise DomainError("followup_source_changed", 409)
        self.booking.project(self.booking.decrypt(current["snapshot_cipher"])["project_version_id"])
        if not data.message.strip() or not now() < data.due_at <= now() + timedelta(days=90):
            raise DomainError("followup_plan_invalid", 422)
        existing = self.repo.all(
            "SELECT state,opted_out FROM followup_task WHERE "
            "tenant_id=%s AND store_id=%s AND case_id=%s",
            (self.actor.tenant_id, self.store, data.case_id),
        )
        if any(r["opted_out"] for r in existing):
            raise DomainError("followup_opted_out", 409)
        if len(existing) >= 200 or any(
            r["state"] in ("awaiting_confirmation", "scheduled") for r in existing
        ):
            raise DomainError("followup_already_open", 409)
        plan = json.dumps(
            {
                "message": data.message.strip(),
                "due_at": data.due_at.isoformat(),
                "case_id": str(data.case_id),
                "case_version": case["version"],
                "channel": "in_app",
            },
            sort_keys=True,
        )
        id = str(uuid4())
        self.repo.execute(
            "INSERT INTO followup_task(id,tenant_id,store_id,visitor_id,case_id,case_version,"
            "created_by,"
            "version,state,due_at,plan_cipher,snapshot_hash,simulated) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,1,'awaiting_confirmation',%s,%s,%s,%s)",
            (
                id,
                self.actor.tenant_id,
                self.store,
                case["visitor_id"],
                case["id"],
                case["version"],
                self.actor.id,
                data.due_at,
                self.booking.cipher().encrypt(plan.encode()).decode(),
                self.booking.hashed(plan),
                case["simulated"],
            ),
        )
        return self.finish(self.row(id), data, raw, "created", request)

    def locked(self, id: str, version: int) -> dict[str, Any]:
        found = self.row(id)
        self.cases.row(str(found["case_id"]))
        row = self.row(id, True)
        if row["version"] != version or row["version"] >= 200:
            raise DomainError("followup_state_conflict", 409)
        return row

    def transition(self, row: dict[str, Any], state: str, opted_out: bool) -> dict[str, Any]:
        self.repo.execute(
            "UPDATE followup_task SET state=%s,opted_out=%s,version=version+1,"
            "updated_at=now() WHERE id=%s",
            (state, opted_out, row["id"]),
        )
        return self.row(str(row["id"]))

    def staff_action(self, id: str, data: FollowupStaffAction, request: str) -> dict[str, Any]:
        if self.actor.kind != "staff":
            raise DomainError("unauthenticated", 401)
        raw, replay = self.command("staff", data, id)
        if replay:
            return self.detail(replay, request)
        row = self.locked(id, data.expected_version)
        if not data.note.strip():
            raise DomainError("invalid_input", 422)
        if data.action == "cancel" and row["state"] not in ("awaiting_confirmation", "scheduled"):
            raise DomainError("followup_state_conflict", 409)
        row = self.transition(
            row, "cancelled" if data.action == "cancel" else row["state"], row["opted_out"]
        )
        return self.finish(row, data, raw, data.action, request)

    def respond(self, id: str, data: FollowupResponse, request: str) -> dict[str, Any]:
        if self.actor.kind != "visitor":
            raise DomainError("unauthenticated", 401)
        raw, replay = self.command("customer", data, id)
        if replay:
            return self.detail(replay, request)
        row = self.locked(id, data.expected_version)
        if not hmac.compare_digest(row["snapshot_hash"], data.snapshot_hash):
            raise DomainError("followup_snapshot_changed", 409)
        if data.confirmation_text != CUSTOMER_TEXT[data.action]:
            raise DomainError("customer_confirmation_required", 422)
        if data.action != "feedback" and (data.result is not None or data.feedback):
            raise DomainError("invalid_input", 422)
        state, opted_out = row["state"], row["opted_out"]
        if data.action in ("accept", "reject"):
            if state != "awaiting_confirmation":
                raise DomainError("followup_state_conflict", 409)
            if data.action == "accept":
                case = self.cases.row(str(row["case_id"]))
                current = self.cases.revisions(case)[-1]
                if case["version"] != row["case_version"] or current["decision"] != "accept":
                    raise DomainError("followup_source_changed", 409)
                self.booking.project(
                    self.booking.decrypt(current["snapshot_cipher"])["project_version_id"]
                )
                if row["due_at"] <= now():
                    raise DomainError("followup_plan_expired", 409)
                grants = self.repo.all(
                    "SELECT g.permission FROM store_grant g JOIN staff s "
                    "ON (s.tenant_id,s.id)=(g.tenant_id,g.staff_id) "
                    "WHERE g.tenant_id=%s AND g.store_id=%s "
                    "AND g.staff_id=%s AND s.active AND (%s OR NOT s.simulated) FOR SHARE OF g,s",
                    (
                        self.actor.tenant_id,
                        self.store,
                        row["created_by"],
                        self.settings.allow_simulated_data,
                    ),
                )
                if not {"customer_read", "customer_manage"}.issubset(
                    {g["permission"] for g in grants}
                ):
                    raise DomainError("followup_author_unavailable", 409)
            state, opted_out = (
                ("scheduled", False) if data.action == "accept" else ("declined", True)
            )
        elif data.action == "feedback":
            if state != "scheduled" or data.result is None:
                raise DomainError("followup_state_conflict", 409)
            state = "completed"
        elif data.action == "cancel":
            if state != "scheduled":
                raise DomainError("followup_state_conflict", 409)
            state, opted_out = "cancelled", True
        elif data.action == "resume":
            if not opted_out or state not in ("declined", "cancelled"):
                raise DomainError("followup_state_conflict", 409)
            opted_out = False
        row = self.transition(row, state, opted_out)
        return self.finish(row, data, raw, data.action, request)
