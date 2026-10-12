"""Trusted capability broker: binds every call to one authenticated actor/run/lease."""

import re
from typing import Any, Literal, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent_policy import GREETING, handoff_answer
from app.consultation_agent import ConsultationAgent, State, validate_draft
from app.consultation_gateway import QwenConsultationGateway
from app.domain import DomainError
from app.graph_adapter import Neo4jKnowledgeGraph
from app.model_gateway import GatewayError
from app.retrieval import RetrievalService
from app.vector_adapter import MilvusVectorStore


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Empty(Input):
    pass


class IDs(Input):
    ids: list[str] = Field(max_length=400)


class Search(Input):
    question: str = Field(min_length=1, max_length=3000)
    limit: int = Field(ge=1, le=3)


class Answer(IDs):
    question: str = Field(min_length=1, max_length=2000)


class Trace(Input):
    node: Literal[
        "classify",
        "fixed",
        "handoff",
        "retrieve",
        "generate",
        "validate",
        "support",
        "model",
        "model_retry",
    ]
    elapsed: int = Field(ge=0, le=60000)
    outcome: str = Field(max_length=80, pattern=r"^[a-z_]+$")


class Get(Input):
    config: dict[str, Any]


class Put(Get):
    checkpoint: dict[str, Any]
    metadata: dict[str, Any]


class Writes(Get):
    writes: list[list[Any]] = Field(max_length=32)
    task_id: str = Field(max_length=128)


class Completion(Input):
    kind: Literal["done"]
    result: dict[str, Any]
    memory: dict[str, Any]
    exportable: bool


class Broker:
    def __init__(self, agent: ConsultationAgent, row: dict[str, Any]) -> None:
        self.agent = agent
        self.store = agent.store
        self.run_id, self.lease = str(row["id"]), str(row["lease_token"])
        self.plan = agent.plan(row)
        self.saver = self.store.checkpointer(self.run_id, self.lease)
        self.resources: list[Any] = []
        self.gateway: Any = agent.injected_gateway
        self.retrieval: Any = agent.injected_retrieval
        self.answers: list[tuple[str, list[str]]] = []

    def close(self) -> None:
        for resource in self.resources:
            resource.close()

    def external(self) -> None:
        if self.gateway is not None and self.retrieval is not None:
            return
        gateway = QwenConsultationGateway(
            self.store.settings, self.agent.reader, self.store.actor, self.plan["deadline"]
        )
        gateway.appointment_declined = (
            bool(self.plan["memory"].get("appointment_declined")) or self.plan["pause_invitation"]
        )
        self.resources.append(gateway)
        if self.gateway is None:
            self.gateway = gateway
        if self.retrieval is None:
            graph = Neo4jKnowledgeGraph(self.store.settings, read_timeout=3)
            vectors = MilvusVectorStore(self.store.settings)
            self.resources.extend([graph, vectors])
            self.retrieval = RetrievalService(
                self.agent.reader, graph, gateway, vectors, self.store.settings.allow_simulated_data
            )

    def current(self) -> dict[str, dict[str, Any]]:
        return {str(row["id"]): row for row in self.agent.reader.evidence(self.store.actor)}

    def ids(self, ids: list[str]) -> list[str]:
        for value in ids:
            UUID(value)
        if len(set(ids)) != len(ids) or not set(ids) <= self.current().keys():
            raise DomainError("sandbox_evidence_scope_denied")
        return ids

    def config(self, value: dict[str, Any]) -> RunnableConfig:
        if set(value) != {"configurable"}:
            raise DomainError("checkpoint_scope_denied")
        options = value["configurable"]
        if not isinstance(options, dict) or not set(options) <= {
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
        }:
            raise DomainError("checkpoint_scope_denied")
        if options.get("thread_id") != self.run_id or options.get("checkpoint_ns", ""):
            raise DomainError("checkpoint_scope_denied")
        if "checkpoint_id" in options:
            UUID(options["checkpoint_id"])
        return cast(RunnableConfig, value)

    def dispatch(self, operation: str, payload: dict[str, Any]) -> Any:
        try:
            return self._dispatch(operation, payload)
        except DomainError as error:
            try:
                self.store.trace(self.run_id, self.lease, "sandbox_rpc_denied", 0, error.code)
            except DomainError:
                pass
            raise

    def _dispatch(self, operation: str, payload: dict[str, Any]) -> Any:
        # No caller-selected actor, tenant, thread, lease, SQL, endpoint or callable.
        self.store.check(self.run_id, self.lease)
        try:
            if operation == "scope.check":
                Empty.model_validate(payload)
                return None
            if operation == "scope.context":
                Empty.model_validate(payload)
                return self.plan["question"], self.plan["previous"], self.plan["memory"]
            if operation == "trace":
                trace = Trace.model_validate(payload)
                self.store.trace(self.run_id, self.lease, trace.node, trace.elapsed, trace.outcome)
                return None
            if operation == "evidence.list":
                Empty.model_validate(payload)
                return list(self.current().values())
            if operation == "evidence.details":
                return self.agent.reader.details(self.ids(IDs.model_validate(payload).ids))
            if operation == "retrieval.search":
                data = Search.model_validate(payload)
                expected = self.plan["topics"].query(
                    self.plan["policy"]["question"], self.plan["keys"], self.plan["explicit"]
                )
                if (
                    data.question != expected
                    or self.plan["policy"]["reason"]
                    or self.plan["policy"]["intent"]
                    in ("greeting", "clarify", "decline", "recall", "support")
                ):
                    raise DomainError("sandbox_question_scope_denied")
                self.external()
                return self.retrieval.search(self.store.actor, expected, data.limit)
            if operation == "model.answer":
                answer_input = Answer.model_validate(payload)
                if (
                    answer_input.question != self.plan["policy"]["question"]
                    or self.plan["policy"]["reason"]
                    or self.plan["policy"]["intent"]
                    in ("greeting", "clarify", "decline", "recall", "support")
                ):
                    raise DomainError("sandbox_question_scope_denied")
                if not 1 <= len(answer_input.ids) <= 3:
                    raise DomainError("sandbox_evidence_scope_denied")
                current = self.current()
                if not set(answer_input.ids) <= current.keys():
                    raise GatewayError("evidence_changed")
                self.external()
                evidence = [current[key] for key in answer_input.ids]
                draft = self.gateway.answer(
                    answer_input.question,
                    self.plan["safe_previous"],
                    evidence,
                    self.plan["dialogue"],
                )
                # Validate in the parent too. Worker-supplied content/history never reaches Gateway.
                self.answers.append(validate_draft(draft, evidence))
                return draft.model_dump()
            if operation == "checkpoint.get":
                row = self.saver.get_tuple(self.config(Get.model_validate(payload).config))
                return list(row) if row else None
            if operation == "checkpoint.put":
                put = Put.model_validate(payload)
                checkpoint: Checkpoint = put.checkpoint  # type: ignore[assignment]
                metadata: CheckpointMetadata = put.metadata  # type: ignore[assignment]
                UUID(checkpoint["id"])
                return self.saver.put(self.config(put.config), checkpoint, metadata, {})
            if operation == "checkpoint.writes":
                writes = Writes.model_validate(payload)
                if any(len(row) != 2 or not isinstance(row[0], str) for row in writes.writes):
                    raise DomainError("sandbox_protocol_denied")
                self.saver.put_writes(
                    self.config(writes.config),
                    [(row[0], row[1]) for row in writes.writes],
                    writes.task_id,
                )
                return None
        except (ValidationError, ValueError, KeyError, TypeError):
            raise DomainError("sandbox_protocol_denied", 503) from None
        raise DomainError("sandbox_operation_denied")

    def validate_completion(
        self, packet: dict[str, Any], message_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        try:
            completion = Completion.model_validate(packet)
            result = completion.result
            if set(result) != {
                "run_id",
                "message_id",
                "thread_id",
                "answer",
                "public_answer",
                "intent",
                "funnel_stage",
                "mode",
                "simulated",
                "disclosure",
                "evidence_ids",
                "evidence",
                "handoff_reason",
                "handoff",
                "action",
                "project_ids",
            }:
                raise ValueError("result_keys")
            policy = self.plan["policy"]
            if (result["run_id"], result["message_id"], result["thread_id"]) != (
                self.run_id,
                message_id,
                self.store.thread_id,
            ):
                raise ValueError("scope")
            if result["intent"] != policy["intent"] or result["funnel_stage"] != policy["stage"]:
                raise ValueError("policy")
            reason = result["handoff_reason"]
            if reason not in (policy["reason"], "evidence_changed", "missing_evidence"):
                raise ValueError("reason")
            if policy["reason"] and reason != policy["reason"]:
                raise ValueError("reason")
            current = self.current()
            refs = result["evidence_ids"]
            if len(refs) > 5 or not set(refs) <= current.keys():
                raise DomainError("evidence_changed", 409)
            cue = self.plan["support"]
            variants = sorted(
                (
                    row
                    for row in current.values()
                    if row["knowledge_key"].startswith(f"comfort-{cue.kind if cue else 'general'}-")
                ),
                key=lambda row: row["knowledge_key"],
            )
            support = variants[int(message_id[-1], 16) % len(variants)] if variants else None
            support_id = str(support["id"]) if support else ""
            fact_refs = [key for key in refs if key != support_id]
            answer, public = result["answer"], result.get("public_answer", "")
            mode = result["mode"]
            if mode == "generated":
                if not any(public == text and fact_refs == ids for text, ids in self.answers):
                    raise ValueError("unverified_answer")
                expected = public
            elif mode == "evidence_fallback":
                if not 1 <= len(fact_refs) <= 2:
                    raise ValueError("fallback")
                expected = "关于这个问题，当前可引用的资料是：\n" + "\n\n".join(
                    current[key]["content"] for key in fact_refs
                )
                if public != expected:
                    raise ValueError("fallback")
            elif mode == "handoff":
                expected = handoff_answer(reason)
                if public:
                    raise ValueError("private_answer")
            elif mode == "fixed":
                intent = policy["intent"]
                if intent == "support":
                    expected = (
                        support["content"]
                        if support
                        else "你可以按自己的节奏来，先不讨论项目也没关系。"
                    )
                elif intent == "greeting":
                    expected = GREETING
                elif intent == "decline":
                    expected = "好的，我们先了解信息。你想问项目介绍、费用核实还是到店流程？"
                elif intent == "recall":
                    first = self.plan["first_topic"]
                    labels = self.plan["topics"].labels(first["keys"]) if first else []
                    expected = (
                        "我们最初聊的是“"
                        + "、".join(labels)
                        + "”。你可以继续这个方向，或告诉我想换的话题。"
                        if labels
                        else "这段对话里还没有可确认的最初项目方向，你可以再告诉我想了解什么。"
                    )
                else:
                    expected = "你想了解哪方面的美容护理、项目或到店咨询？可以直接描述你的问题。"
                if public:
                    raise ValueError("fixed_answer")
            else:
                raise ValueError("mode")
            if support is not None and support_id in refs and policy["intent"] != "support":
                expected = support["content"].split("\n\n", 1)[0] + " " + expected
            if answer != expected or (fact_refs and mode not in ("generated", "evidence_fallback")):
                raise ValueError("answer")
            if (
                self.plan["memory"].get("appointment_declined") or self.plan["pause_invitation"]
            ) and re.search(
                r"建议你.{0,6}(预约|到店)|是否(想|需要|愿意|希望).{0,6}预约|要不要.{0,6}预约|现在(就|可以|帮你).{0,6}预约|帮你.{0,6}预约|如果.{0,6}(愿意|有兴趣).{0,6}预约",
                answer,
            ):
                raise ValueError("declined")
            action = (
                {"type": "visit_interest", "submitted": False}
                if policy["intent"] == "visit_interest"
                else None
            )
            if result["action"] != action or result["handoff"] is not None:
                raise ValueError("business")
            visible = {row["id"] for row in self.agent.catalog.projects(self.store.actor)}
            if len(result["project_ids"]) > 3 or not set(result["project_ids"]) <= visible:
                raise ValueError("projects")
            state: State = {"intent": policy["intent"], "stage": policy["stage"], "reason": reason}
            memory = self.agent.memory_snapshot(self.plan, state, message_id)
            exportable = not bool(policy["reason"]) and policy["intent"] not in (
                "clarify",
                "support",
            )
            if completion.memory != memory or completion.exportable != exportable:
                raise ValueError("memory")
            # Evidence metadata and business status are reconstructed by the trusted parent.
            result["evidence"] = [
                {
                    "id": key,
                    "title": current[key]["title"],
                    "source": current[key]["source"],
                    "version": current[key]["version"],
                    "simulated": current[key]["simulated"],
                    "review_scope": current[key].get("review_scope") or "standard",
                }
                for key in refs
            ]
            result["simulated"] = any(current[key]["simulated"] for key in refs)
            result["disclosure"] = (
                "演示场景：机构、供给与价格为虚构；模拟科普复核不代表真实医学批准"
                if result["simulated"]
                else ""
            )
            result.pop("projects", None)
            return result, memory, exportable
        except (ValidationError, ValueError, KeyError, TypeError):
            raise DomainError("sandbox_result_denied", 503) from None
