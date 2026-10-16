"""Account restoration and consented, bounded first-party memory; never model evidence."""

import re
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.domain import Actor, DomainError, Repository, now
from app.security import digest, password_hash, token, verify_password

MemoryKey = Literal["comfort", "visit_time", "budget", "communication"]
PREFERENCES: dict[str, tuple[str, ...]] = {
    "comfort": ("担心疼痛，希望先了解舒适度", "不再担心疼痛"),
    "visit_time": ("周末方便到店", "工作日方便到店", "晚上方便到店"),
    "budget": ("希望先了解价格，谨慎控制预算", "预算灵活，先了解项目"),
    "communication": ("希望先了解信息，暂不接受预约邀请", "希望进一步了解预约流程"),
}
RECALL = re.compile(r"记得.{0,12}(我|偏好)|我的偏好|上次.{0,10}(说|聊|担心|时间)|记住了什么")


class CustomerCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=10, max_length=128)
    # Registering binds only the authenticated current visitor, never a supplied ID/phone.
    bind_current: bool = False
    enable_memory: bool = False


class MemorySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_enabled: bool
    behavior_enabled: bool


class BehaviorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["project_view", "category_view"]
    target: str = Field(min_length=1, max_length=80)


def extract_preferences(text: str) -> dict[str, str]:
    """Only unambiguous explicit first-person preferences, never verbatim arbitrary text."""
    if not re.search(r"我|本人", text) or re.search(
        r"如果|假如|比如|例如|朋友|客户|她|他|[“”\"]|忽略|指令|系统|病史|怀孕|用药|过敏", text
    ):
        return {}
    result: dict[str, str] = {}
    if re.search(r"我(?:现在|已经|其实)?(?:不怕疼|不再怕疼|不担心疼)", text):
        result["comfort"] = PREFERENCES["comfort"][1]
    elif re.search(r"我(?:比较|很|有点|特别)?怕疼|我.{0,4}担心.{0,2}疼", text):
        result["comfort"] = PREFERENCES["comfort"][0]
    times = [
        value
        for pattern, value in (
            (
                r"我(?:只有|只能|一般|通常)?周末(?:才)?(?:有空|方便|能来|到店)",
                PREFERENCES["visit_time"][0],
            ),
            (
                r"我(?:只有|只能|一般|通常)?工作日(?:才)?(?:有空|方便|能来|到店)",
                PREFERENCES["visit_time"][1],
            ),
            (
                r"我(?:只有|只能|一般|通常)?晚上(?:才)?(?:有空|方便|能来|到店)",
                PREFERENCES["visit_time"][2],
            ),
        )
        if re.search(pattern, text)
    ]
    if len(times) == 1:
        result["visit_time"] = times[0]
    if re.search(r"我.{0,4}(?:预算有限|控制预算|先了解价格|先看价格)", text):
        result["budget"] = PREFERENCES["budget"][0]
    elif re.search(r"我.{0,4}预算(?:比较)?灵活", text):
        result["budget"] = PREFERENCES["budget"][1]
    if re.search(r"我.{0,4}(?:先不预约|暂不预约|不想预约|不接受推销)", text):
        result["communication"] = PREFERENCES["communication"][0]
    elif re.search(r"我(?:现在)?想了解预约流程", text):
        result["communication"] = PREFERENCES["communication"][1]
    return result


def is_preference_statement(text: str) -> bool:
    # Only standalone supported clauses, never a health question or another request.
    clauses = [clause.strip() for clause in re.split(r"[，,；;。！!\n]", text) if clause.strip()]
    return bool(clauses) and all(
        bool(extract_preferences(clause))
        and bool(
            re.fullmatch(
                r"我(?:现在|已经|其实|比较|很|有点|特别|只有|只能|一般|通常)?"
                r"(?:不怕疼|不再怕疼|不担心疼|怕疼|担心疼|"
                r"(?:周末|工作日|晚上)(?:才)?(?:有空|方便|能来|到店)|"
                r"预算有限|控制预算|先了解价格|先看价格|预算(?:比较)?灵活|"
                r"先不预约|暂不预约|不想预约|不接受推销|想了解预约流程)",
                clause,
            )
        )
        for clause in clauses
    )


def preference_acknowledgement(text: str) -> str | None:
    if not is_preference_statement(text):
        return None
    return (
        "了解，你的偏好是："
        + "；".join(extract_preferences(text).values())
        + "。我们可以按你的节奏继续了解。"
    )


class CustomerService:
    def __init__(self, repo: Repository, settings: Settings, actor: Actor) -> None:
        self.repo, self.settings, self.actor = repo, settings, actor

    def account(self) -> dict[str, Any] | None:
        a = self.actor
        return (
            self.repo.one(
                "SELECT c.id,c.username,v.memory_enabled,v.behavior_enabled,v.memory_generation "
                "FROM auth_session s "
                "JOIN visitor v ON v.id=s.visitor_id AND v.customer_id=s.customer_id "
                "JOIN customer_account c ON (c.tenant_id,c.id)=(s.tenant_id,s.customer_id) "
                "WHERE s.id=%s AND s.tenant_id=%s AND s.store_id=%s AND s.visitor_id=%s "
                "AND s.revoked_at IS NULL AND s.expires_at>now()",
                (a.session_id, a.tenant_id, a.store_id, a.id),
            )
            if a.kind == "visitor"
            else None
        )

    def require_account(self) -> dict[str, Any]:
        row = self.account()
        if not row:
            raise DomainError("customer_login_required", 401)
        return row

    def authenticate(
        self, data: CustomerCredentials, register: bool, source: str, request: str
    ) -> dict[str, Any]:
        # The caller commits throttle increments even on failed authentication.
        if self.account():
            return {"error": "customer_already_logged_in"}
        username = data.username.casefold()
        bucket = digest("customer|" + self.actor.tenant_id + "|" + username + "|" + source)
        self.repo.execute(
            "INSERT INTO login_bucket VALUES(%s,1,now()) ON CONFLICT(bucket_hash) "
            "DO UPDATE SET attempts=CASE WHEN login_bucket.window_start<now()-interval "
            "'15 minutes' THEN 1 ELSE login_bucket.attempts+1 END,window_start=CASE "
            "WHEN login_bucket.window_start<now()-interval '15 minutes' THEN now() "
            "ELSE login_bucket.window_start END",
            (bucket,),
        )
        row = self.repo.one("SELECT attempts FROM login_bucket WHERE bucket_hash=%s", (bucket,))
        if row and row["attempts"] > 10:
            return {"error": "login_throttled"}
        guest = self.repo.one(
            "SELECT id,customer_id FROM visitor WHERE id=%s FOR UPDATE",
            (self.actor.id,),
        )
        if not guest or guest["customer_id"] is not None:
            return {"error": "customer_already_logged_in"}
        # Serialize same-account registration / first login into a new store.
        self.repo.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (self.actor.tenant_id + "|" + username,),
        )
        account = self.repo.one(
            "SELECT * FROM customer_account WHERE tenant_id=%s AND username=%s",
            (self.actor.tenant_id, username),
        )
        if register:
            if not data.bind_current:
                return {"error": "binding_consent_required"}
            if not data.enable_memory:
                return {"error": "memory_consent_required"}
            if account:
                return {"error": "customer_name_unavailable"}
            account = {"id": str(uuid4()), "username": username}
            self.repo.execute(
                "INSERT INTO customer_account(id,tenant_id,username,password_hash) "
                "VALUES(%s,%s,%s,%s)",
                (account["id"], self.actor.tenant_id, username, password_hash(data.password)),
            )
        elif (
            not verify_password(
                data.password,
                account["password_hash"] if account else password_hash("dummy-password"),
            )
            or not account
        ):
            return {"error": "invalid_credentials"}
        owner = self.repo.one(
            "SELECT id FROM visitor WHERE tenant_id=%s AND store_id=%s AND customer_id=%s",
            (self.actor.tenant_id, self.actor.store_id, account["id"]),
        )
        visitor_id = str(owner["id"]) if owner else self.actor.id
        if not owner:
            if not data.bind_current:
                return {"error": "binding_consent_required"}
            self.repo.execute(
                "UPDATE visitor SET customer_id=%s WHERE id=%s",
                (account["id"], visitor_id),
            )
            # A copied pre-login guest credential must never gain customer privileges.
            self.repo.execute(
                "UPDATE auth_session SET revoked_at=now() WHERE visitor_id=%s",
                (visitor_id,),
            )
        else:
            self.repo.execute(
                "UPDATE auth_session SET revoked_at=now() WHERE id=%s",
                (self.actor.session_id,),
            )
        credential, csrf, session_id = token(), token(), str(uuid4())
        if data.enable_memory:
            self.repo.execute(
                "UPDATE visitor SET memory_enabled=true WHERE id=%s",
                (visitor_id,),
            )
        self.repo.execute(
            "INSERT INTO auth_session(id,tenant_id,visitor_id,store_id,customer_id,"
            "token_hash,csrf_hash,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                session_id,
                self.actor.tenant_id,
                visitor_id,
                self.actor.store_id,
                account["id"],
                digest(credential),
                digest(csrf),
                now() + timedelta(hours=self.settings.session_hours),
            ),
        )
        self.repo.audit(
            self.actor,
            "customer.register" if register else "customer.login",
            str(account["id"]),
            request,
        )
        return {
            "credential": credential,
            "csrf_token": csrf,
            "visitor_id": visitor_id,
            "restored": bool(owner),
            "username": account["username"],
        }

    def profile(self) -> dict[str, Any]:
        row = self.account()
        if not row:
            return {"customer": None, "memories": [], "behaviors": []}
        return {
            "customer": {
                "username": row["username"],
                "memory_enabled": row["memory_enabled"],
                "behavior_enabled": row["behavior_enabled"],
            },
            "memories": self.memories(),
            "behaviors": self.repo.all(
                "SELECT event,target,occurred_at FROM customer_behavior WHERE visitor_id=%s "
                "AND occurred_at>now()-interval '90 days' ORDER BY occurred_at DESC LIMIT 30",
                (self.actor.id,),
            )
            if row["behavior_enabled"]
            else [],
        }

    def session(self) -> dict[str, Any]:
        row = self.account()
        return {"customer": {"username": row["username"]} if row else None}

    def memories(self, exclude_thread: str | None = None) -> list[dict[str, Any]]:
        row = self.account()
        if not row or not row["memory_enabled"]:
            return []
        return self.repo.all(
            "SELECT key,value,source_thread_id,updated_at,expires_at FROM customer_memory "
            "WHERE visitor_id=%s AND expires_at>now() "
            "AND (%s::uuid IS NULL OR source_thread_id<>%s::uuid) ORDER BY updated_at DESC LIMIT 8",
            (self.actor.id, exclude_thread, exclude_thread),
        )

    def settings_update(self, data: MemorySettings) -> dict[str, Any]:
        self.require_account()
        self.repo.one("SELECT id FROM visitor WHERE id=%s FOR UPDATE", (self.actor.id,))
        self.repo.execute(
            "UPDATE visitor SET memory_enabled=%s,behavior_enabled=%s,"
            "memory_generation=memory_generation+1 WHERE id=%s",
            (data.memory_enabled, data.behavior_enabled, self.actor.id),
        )
        if not data.memory_enabled:
            self.repo.execute("DELETE FROM customer_memory WHERE visitor_id=%s", (self.actor.id,))
        if not data.behavior_enabled:
            self.repo.execute("DELETE FROM customer_behavior WHERE visitor_id=%s", (self.actor.id,))
        return self.profile()

    def forget(self, key: MemoryKey | Literal["all"]) -> None:
        self.require_account()
        self.repo.one("SELECT id FROM visitor WHERE id=%s FOR UPDATE", (self.actor.id,))
        self.repo.execute(
            "UPDATE visitor SET memory_generation=memory_generation+1 WHERE id=%s",
            (self.actor.id,),
        )
        self.repo.execute(
            "DELETE FROM customer_memory WHERE visitor_id=%s AND (%s='all' OR key=%s)",
            (self.actor.id, key, key),
        )

    def capture(self, text: str, thread: str, run: str, allow: bool) -> None:
        row = self.account()
        if not row or not row["memory_enabled"] or not allow:
            return
        # Serialize against disabling/deleting memories. Never replay historical messages.
        self.repo.one("SELECT id FROM visitor WHERE id=%s FOR UPDATE", (self.actor.id,))
        row = self.account()
        if not row or not row["memory_enabled"]:
            return
        generation = self.repo.one(
            "SELECT customer_memory_generation FROM agent_run WHERE id=%s AND visitor_id=%s "
            "AND thread_id=%s",
            (run, self.actor.id, thread),
        )
        if not generation or generation["customer_memory_generation"] != row["memory_generation"]:
            return
        for key, value in extract_preferences(text).items():
            self.repo.execute(
                "INSERT INTO customer_memory(visitor_id,key,value,source_thread_id,source_run_id) "
                "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(visitor_id,key) DO UPDATE SET "
                "value=excluded.value,source_thread_id=excluded.source_thread_id,"
                "source_run_id=excluded.source_run_id,updated_at=now(),"
                "expires_at=now()+interval '90 days' WHERE "
                "(SELECT created_at FROM agent_run WHERE id=customer_memory.source_run_id) "
                "<=(SELECT created_at FROM agent_run WHERE id=excluded.source_run_id)",
                (self.actor.id, key, value, thread, run),
            )

    def behavior(self, event: str, target: str) -> None:
        row = self.account()
        if not row or not row["behavior_enabled"]:
            return
        if event == "category_view" and target not in ("all", "care", "medical"):
            raise DomainError("invalid_input", 422)
        if event == "project_view":
            try:
                UUID(target)
            except ValueError:
                raise DomainError("invalid_input", 422) from None
            if not self.repo.one(
                "SELECT id FROM knowledge_version WHERE id=%s AND tenant_id=%s AND store_id=%s "
                "AND status='published' AND valid_until>now()",
                (target, self.actor.tenant_id, self.actor.store_id),
            ):
                raise DomainError("project_unavailable", 404)
        self.repo.one("SELECT id FROM visitor WHERE id=%s FOR UPDATE", (self.actor.id,))
        row = self.account()
        if not row or not row["behavior_enabled"]:
            return
        count = self.repo.one(
            "SELECT count(*) AS n FROM customer_behavior WHERE visitor_id=%s "
            "AND occurred_at>now()-interval '1 minute'",
            (self.actor.id,),
        )
        if count and count["n"] >= 30:
            return
        if event == "consultation_started" and self.repo.one(
            "SELECT id FROM customer_behavior WHERE visitor_id=%s AND event=%s AND target=%s",
            (self.actor.id, event, target),
        ):
            return
        self.repo.execute(
            "DELETE FROM customer_behavior WHERE visitor_id=%s "
            "AND occurred_at<now()-interval '90 days'",
            (self.actor.id,),
        )
        self.repo.execute(
            "INSERT INTO customer_behavior(id,visitor_id,event,target) VALUES(%s,%s,%s,%s)",
            (str(uuid4()), self.actor.id, event, target),
        )


def recall_answer(question: str, memories: list[dict[str, Any]]) -> str | None:
    if not RECALL.search(question):
        return None
    values = [r["value"] for r in memories if r["value"] in PREFERENCES.get(r["key"], ())]
    if not values:
        return "目前没有可用的跨对话偏好记忆。登录后可在客户中心开启，之后明确告诉我你的偏好。"
    return (
        "你之前明确告诉我的偏好是："
        + "；".join(values)
        + "。这些偏好还适用吗？如果有变化，可以直接告诉我。"
    )


def personalize_answer(
    question: str, result: dict[str, Any], memories: list[dict[str, Any]]
) -> None:
    """Trusted local projection only. Personal facts never enter public_answer/model history."""
    if result.get("handoff_reason") or result.get("intent") in ("support", "decline"):
        return
    personal = (
        recall_answer(question, memories) or preference_acknowledgement(question)
        if result.get("intent") == "recall"
        else None
    )
    if personal:
        result.update(answer=personal, public_answer="")
        return
    values = {r["key"]: r["value"] for r in memories if r["value"] in PREFERENCES.get(r["key"], ())}
    if result.get("mode") in ("generated", "evidence_fallback"):
        for key, pattern in (
            ("visit_time", r"到店时间|周末|工作日|几点"),
            ("budget", r"预算|价格|多少钱"),
        ):
            if key in values and re.search(pattern, question):
                result["answer"] += (
                    "\n\n你之前提到：" + values[key] + "。如果偏好有变化，可以告诉我。"
                )
                break
