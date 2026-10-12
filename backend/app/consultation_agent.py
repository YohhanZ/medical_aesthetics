"""LangGraph nodes with PostgreSQL authority and a bounded, reference-only persisted state."""

import logging
import re
import time
import traceback
from collections.abc import Callable
from typing import Any, TypedDict, cast

from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from app.agent_policy import GREETING, classify, handoff_answer, public_question
from app.agent_repository import AgentStore
from app.catalog import CatalogService
from app.consultation_gateway import AnswerGateway, Draft, QwenConsultationGateway
from app.conversation_context import HISTORY_REFERENCE, PublicTopics
from app.domain import DomainError
from app.emotion_support import detect_support
from app.graph_adapter import Neo4jKnowledgeGraph
from app.model_gateway import GatewayError, redact_contacts
from app.retrieval import EvidenceReader, PostgresEvidenceReader, RetrievalService
from app.vector_adapter import MilvusVectorStore


class State(TypedDict, total=False):
    run_id: str
    intent: str
    stage: str
    reason: str
    answer: str
    evidence_ids: list[str]
    mode: str
    public_answer: str


def validate_draft(draft: Draft, evidence: list[dict[str, Any]]) -> tuple[str, list[str]]:
    allowed = {str(row["id"]): row for row in evidence}
    texts, refs = [], []
    for section in draft.sections:
        row = allowed.get(section.evidence_id)
        if not row or section.quote not in redact_contacts(row["content"]):
            raise GatewayError("answer_evidence_invalid")
        text = section.text
        claim_probe = re.sub(
            r"(?:门店|机构).{0,8}确认.{0,8}(?:后|才|才能|方可).{0,10}已确认预约", "", text
        )
        if re.search(
            r"https?://|www\.|适合你|保证有效|保证疗效|绝对安全|零风险|永久有效|"
            r"已.{0,3}(预约|付款|确认到店)|必须购买|"
            r"你(?:有|患有|得了).{0,4}(抑郁症|焦虑症)|不做.{0,6}(越来越丑|越来越难看)|"
            r"医美(?:能|可以|会).{0,4}(治愈|治好).{0,6}(抑郁|焦虑|难过)|"
            r"做.{0,4}(医美|美容).{0,4}(就能|才能).{0,8}(挽回|治愈)",
            claim_probe,
        ):
            raise GatewayError("answer_policy_denied")
        if redact_contacts(text) != text:
            raise GatewayError("answer_policy_denied")
        if any(number not in row["content"] for number in re.findall(r"\d+(?:\.\d+)?", text)):
            raise GatewayError("answer_fact_unsupported")
        texts.append(text)
        refs.append(section.evidence_id)
    return "\n\n".join(texts), list(dict.fromkeys(refs))


class ConsultationAgent:
    def __init__(
        self,
        store: AgentStore,
        retrieval: RetrievalService | None = None,
        gateway: AnswerGateway | None = None,
        reader: EvidenceReader | None = None,
    ) -> None:
        self.store, self.settings, self.actor = store, store.settings, store.actor
        self.reader = reader or PostgresEvidenceReader(self.settings)
        self.catalog = CatalogService(self.reader)
        self.injected_retrieval, self.injected_gateway = retrieval, gateway

    def fresh_result(self, result: dict[str, Any]) -> dict[str, Any]:
        allowed = {str(row["id"]) for row in self.reader.evidence(self.actor)}
        if not set(result.get("evidence_ids", [])) <= allowed:
            return {
                **result,
                "answer": handoff_answer("evidence_changed"),
                "public_answer": "",
                "evidence_ids": [],
                "evidence": [],
                "handoff_reason": "evidence_changed",
                "mode": "stale",
                "project_ids": [],
                "projects": [],
            }
        project_ids = result.get("project_ids", [])
        visible = self.catalog.projects(self.actor) if project_ids else []
        return {**result, "projects": [row for row in visible if row["id"] in project_ids]}

    def history(self, limit: int, offset: int, recent: bool = False) -> list[dict[str, Any]]:
        rows = self.store.history(limit, offset, recent)
        for row in rows:
            if row["role"] == "assistant" and row["result"]:
                row["result"] = self.fresh_result(row["result"])
                row["content"] = row["result"]["answer"]
        return rows

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.store.run(run_id)
        if row["result"]:
            row["result"] = self.fresh_result(row["result"])
        return row

    def send(self, message_id: str, text: str) -> dict[str, Any]:
        row = self.store.claim(message_id, text)
        if row["status"] == "completed":
            return self.fresh_result(row["result"])
        run_id, lease = str(row["id"]), str(row["lease_token"])
        resources: list[Any] = []
        try:
            return self._execute(row, message_id, resources)
        except Exception as error:
            frame = traceback.extract_tb(error.__traceback__)[-1]
            logging.getLogger(__name__).warning(
                "Agent failure category=%s location=%s:%s",
                type(error).__name__,
                frame.name,
                frame.lineno,
            )
            code = error.code if isinstance(error, DomainError) else "agent_unavailable"
            self.store.fail(run_id, lease, code)
            if isinstance(error, DomainError):
                raise
            raise DomainError("agent_unavailable", 503) from None
        finally:
            for resource in resources:
                resource.close()

    def plan(self, row: dict[str, Any]) -> dict[str, Any]:
        run_id, lease = str(row["id"]), str(row["lease_token"])
        question, previous, memory = self.store.context(run_id)
        deadline = time.monotonic() + 30
        safe_previous: list[str] = []
        for item in previous:
            try:
                safe_previous.append(public_question(item["content"])[:500])
            except GatewayError:
                pass
        projects = self.catalog.projects(self.actor)
        topics = PublicTopics(projects)
        active_topic = topics.resolve(memory, "active_topic")
        first_topic = topics.resolve(memory, "first_topic")
        policy = classify(
            question,
            bool(safe_previous) or bool(active_topic),
            bool(memory.get("medical_pending")),
            bool(memory.get("crisis_pending")),
        )
        support = detect_support(question)
        pause_invitation = bool(support and support.pause_invitation)
        explicit = topics.match(policy["question"]) if not policy["reason"] else []
        if not first_topic:
            for source in memory.get("_initial_public_sources", []):
                try:
                    public_question(source["content"])
                except GatewayError:
                    continue
                earliest = topics.match(source["content"])
                if earliest:
                    first_topic = topics.record(
                        earliest, str(source["run_id"]), str(source["message_id"])
                    )
                    break
        keys = explicit or (active_topic["keys"] if active_topic else [])
        if (
            explicit
            and active_topic
            and re.search(r"(它|这个).{0,6}(和|跟|与)", policy["question"])
        ):
            keys = list(dict.fromkeys(explicit + active_topic["keys"]))[:3]
        if active_topic and active_topic["question"] not in safe_previous:
            safe_previous = [*safe_previous[-3:], active_topic["question"][:500]]
        current_evidence = {str(item["id"]): item for item in self.reader.evidence(self.actor)}
        dialogue = []
        for item in previous:
            result = item.get("result") or {}
            refs = result.get("evidence_ids", [])
            if result.get("mode") not in ("generated", "evidence_fallback") or result.get(
                "handoff_reason"
            ):
                continue
            if refs and set(refs) <= set(current_evidence):
                try:
                    dialogue.append(
                        {
                            "question": public_question(item["content"])[:500],
                            "answer": result.get("public_answer", result["answer"])[:1200],
                            "evidence_ids": refs,
                        }
                    )
                except GatewayError:
                    continue
        return {
            "run_id": run_id,
            "lease": lease,
            "question": question,
            "previous": previous,
            "memory": memory,
            "deadline": deadline,
            "safe_previous": safe_previous,
            "projects": projects,
            "topics": topics,
            "active_topic": active_topic,
            "first_topic": first_topic,
            "policy": policy,
            "support": support,
            "pause_invitation": pause_invitation,
            "explicit": explicit,
            "keys": keys,
            "dialogue": dialogue,
            "current_evidence": current_evidence,
        }

    def memory_snapshot(
        self, plan: dict[str, Any], state: State, message_id: str
    ) -> dict[str, Any]:
        safe_previous = plan["safe_previous"]
        run_id = plan["run_id"]
        previous = plan["previous"]
        memory = plan["memory"]
        pause_invitation = plan["pause_invitation"]
        policy = plan["policy"]
        question = plan["question"]
        first_topic = plan["first_topic"]
        active_topic = plan["active_topic"]
        explicit = plan["explicit"]
        topics = plan["topics"]
        compressed = {
            "source_run_id": run_id,
            "last_intent": state["intent"],
            "last_stage": state["stage"],
            "source_message_ids": [str(item["id"]) for item in previous],
            "appointment_declined": state["intent"] == "decline"
            or pause_invitation
            or (memory.get("appointment_declined", False) and state["intent"] != "visit_interest"),
            "recent_public_questions": safe_previous[-4:],
            "contains_medical_facts": False,
            "crisis_pending": policy["reason"] == "emotional_crisis",
            "medical_pending": policy["reason"] == "personal_medical"
            or (
                bool(memory.get("medical_pending"))
                and not re.search(r"只想了解.*流程|回到.*流程", question)
            ),
        }
        for field, record in (("first_topic", first_topic), ("active_topic", active_topic)):
            if record:
                compressed[field] = {
                    key: record[key] for key in ("keys", "source_run_id", "source_message_id")
                }
        if explicit and not policy["reason"]:
            compressed["active_topic"] = topics.record(explicit, run_id, message_id)
            if not first_topic:
                compressed["first_topic"] = topics.record(explicit, run_id, message_id)
        return compressed

    def _execute(
        self, row: dict[str, Any], message_id: str, resources: list[Any]
    ) -> dict[str, Any]:
        plan = self.plan(row)
        run_id = plan["run_id"]
        lease = plan["lease"]
        memory = plan["memory"]
        deadline = plan["deadline"]
        safe_previous = plan["safe_previous"]
        topics = plan["topics"]
        first_topic = plan["first_topic"]
        policy = plan["policy"]
        support = plan["support"]
        pause_invitation = plan["pause_invitation"]
        explicit = plan["explicit"]
        keys = plan["keys"]
        dialogue = plan["dialogue"]
        evidence: list[dict[str, Any]] = []
        retrieval = self.injected_retrieval
        gateway = self.injected_gateway
        # Lazily construct external clients only for ordinary supported questions.
        if (
            (retrieval is None or gateway is None)
            and not policy["reason"]
            and policy["intent"]
            not in (
                "greeting",
                "clarify",
                "decline",
                "recall",
                "support",
            )
        ):
            real_gateway = QwenConsultationGateway(self.settings, self.reader, self.actor, deadline)
            real_gateway.appointment_declined = (
                bool(memory.get("appointment_declined")) or pause_invitation
            )
            resources.append(real_gateway)
            if gateway is None:
                gateway = real_gateway
            if retrieval is None:
                knowledge_graph = Neo4jKnowledgeGraph(self.settings, read_timeout=3)
                resources.append(knowledge_graph)
                vectors = MilvusVectorStore(self.settings)
                resources.append(vectors)
                retrieval = RetrievalService(
                    self.reader,
                    knowledge_graph,
                    real_gateway,
                    vectors,
                    self.settings.allow_simulated_data,
                )

        def classify_node(state: State) -> State:
            return {
                "intent": policy["intent"],
                "stage": policy["stage"],
                "reason": policy["reason"],
                "answer": "",
                "evidence_ids": [],
                "mode": "none",
            }

        def fixed_node(state: State) -> State:
            if state["intent"] == "support":
                return {"answer": "", "mode": "fixed"}
            if state["intent"] == "recall":
                labels = topics.labels(first_topic["keys"]) if first_topic else []
                answer = (
                    "我们最初聊的是“"
                    + "、".join(labels)
                    + "”。你可以继续这个方向，或告诉我想换的话题。"
                    if labels
                    else "这段对话里还没有可确认的最初项目方向，你可以再告诉我想了解什么。"
                )
                return {"answer": answer, "mode": "fixed"}
            answer = (
                GREETING
                if state["intent"] == "greeting"
                else (
                    "好的，我们先了解信息。你想问项目介绍、费用核实还是到店流程？"
                    if state["intent"] == "decline"
                    else "你想了解哪方面的美容护理、项目或到店咨询？可以直接描述你的问题。"
                )
            )
            return {"answer": answer, "mode": "fixed"}

        def handoff_node(state: State) -> State:
            return {
                "answer": handoff_answer(state["reason"]),
                "evidence_ids": [],
                "mode": "handoff",
            }

        def retrieve_node(state: State) -> State:
            nonlocal evidence
            assert retrieval
            query = policy["question"]
            query = topics.query(query, keys, explicit)
            result = retrieval.search(self.actor, query, limit=3)
            current = {str(item["id"]): item for item in self.reader.evidence(self.actor)}
            evidence = topics.rank(policy["question"], keys, result["items"], current)
            if HISTORY_REFERENCE.search(policy["question"]) and dialogue:
                supporting = [
                    current[key] for key in dialogue[-1]["evidence_ids"] if key in current
                ]
                evidence = list({str(r["id"]): r for r in supporting + evidence}.values())[:3]
            if not evidence:
                return {"reason": "missing_evidence", "mode": "none"}
            return {
                "evidence_ids": [str(item["id"]) for item in evidence],
                "mode": result["method"],
            }

        def generate_node(state: State) -> State:
            assert gateway
            current = {str(item["id"]): item for item in self.reader.evidence(self.actor)}
            if not set(state["evidence_ids"]) <= set(current):
                return {
                    "reason": "evidence_changed",
                    "answer": handoff_answer("evidence_changed"),
                    "evidence_ids": [],
                    "mode": "handoff",
                }
            active = [current[key] for key in state["evidence_ids"]]
            error_code = "model_unavailable"
            for attempt in range(2):
                try:
                    answer, refs = validate_draft(
                        gateway.answer(policy["question"], safe_previous, active, dialogue), active
                    )
                    if (memory.get("appointment_declined") or pause_invitation) and re.search(
                        r"建议你.{0,6}(预约|到店)|是否(想|需要|愿意|希望).{0,6}预约|"
                        r"要不要.{0,6}预约|现在(就|可以|帮你).{0,6}预约|"
                        r"帮你.{0,6}预约|如果.{0,6}(愿意|有兴趣).{0,6}预约",
                        answer,
                    ):
                        raise GatewayError("marketing_declined")
                    return {"answer": answer, "evidence_ids": refs, "mode": "generated"}
                except GatewayError as error:
                    error_code = error.code
                    if (
                        attempt == 0
                        and error.code
                        in (
                            "invalid_model_response",
                            "answer_evidence_invalid",
                            "answer_fact_unsupported",
                        )
                        and time.monotonic() < deadline - 2
                    ):
                        self.store.trace(run_id, lease, "model_retry", 0, error.code)
                        continue
                    break
            # Retry never bypasses validation. Unchecked drafts are never returned or checkpointed.
            self.store.trace(run_id, lease, "model", 0, error_code)
            fallback = active[:2] if len(keys) > 1 else active[:1]
            return {
                "answer": "关于这个问题，当前可引用的资料是：\n"
                + "\n\n".join(item["content"] for item in fallback),
                "evidence_ids": [str(item["id"]) for item in fallback],
                "mode": "evidence_fallback",
            }

        def validate_node(state: State) -> State:
            if state.get("evidence_ids"):
                current = {str(item["id"]) for item in self.reader.evidence(self.actor)}
                if not set(state["evidence_ids"]) <= current:
                    return {
                        "answer": handoff_answer("evidence_changed"),
                        "reason": "evidence_changed",
                        "evidence_ids": [],
                        "mode": "handoff",
                    }
            return {}

        def support_node(state: State) -> State:
            # This node never exports cues, raw feelings or relationship details to a model.
            if state.get("reason") in (
                "emotional_crisis",
                "urgent_health",
                "unauthorized_request",
                "private_record",
            ):
                return {}
            current = self.reader.evidence(self.actor)
            kind = support.kind if support else "general"
            variants = sorted(
                (r for r in current if r["knowledge_key"].startswith(f"comfort-{kind}-")),
                key=lambda r: r["knowledge_key"],
            )
            selected = variants[int(message_id[-1], 16) % len(variants)] if variants else None
            if state["intent"] == "support":
                return {
                    "answer": selected["content"]
                    if selected
                    else "你可以按自己的节奏来，先不讨论项目也没关系。",
                    "public_answer": "",
                    "evidence_ids": [str(selected["id"])] if selected else [],
                }
            if not selected:
                return {}
            public_answer = (
                state["answer"] if state["mode"] in ("generated", "evidence_fallback") else ""
            )
            opening = str(selected["content"]).split("\n\n", 1)[0]
            return {
                "answer": opening + " " + state["answer"],
                "public_answer": public_answer,
                "evidence_ids": list(
                    dict.fromkeys(state.get("evidence_ids", []) + [str(selected["id"])])
                ),
            }

        def wrap(name: str, node: Callable[[State], State]) -> Callable[[State], State]:
            def execute(state: State) -> State:
                self.store.check(run_id, lease)
                started = time.monotonic()
                value = node(state)
                self.store.trace(
                    run_id,
                    lease,
                    name,
                    int((time.monotonic() - started) * 1000),
                    value.get("mode", "ok"),
                )
                return value

            return execute

        builder = StateGraph(State)
        for name, node in (
            ("classify", classify_node),
            ("fixed", fixed_node),
            ("handoff", handoff_node),
            ("retrieve", retrieve_node),
            ("generate", generate_node),
            ("validate", validate_node),
            ("support", support_node),
        ):
            builder.add_node(name, RunnableLambda(wrap(name, node)))
        builder.add_edge(START, "classify")
        builder.add_conditional_edges(
            "classify",
            lambda state: (
                "handoff"
                if state["reason"]
                else "fixed"
                if state["intent"] in ("greeting", "decline", "clarify", "recall", "support")
                else "retrieve"
            ),
        )
        builder.add_conditional_edges(
            "retrieve", lambda state: "handoff" if state["reason"] else "generate"
        )
        for name in ("fixed", "handoff", "generate"):
            builder.add_conditional_edges(
                name,
                lambda state: "support" if support or state["intent"] == "support" else "validate",
            )
        builder.add_edge("support", "validate")
        builder.add_edge("validate", END)
        saver = self.store.checkpointer(run_id, lease)
        graph = builder.compile(checkpointer=saver)
        config: RunnableConfig = {"configurable": {"thread_id": run_id}, "recursion_limit": 12}
        # Explicitly prevent automatic SDK exports of prompts, state and raw messages.
        with tracing_context(enabled=False):
            existing = saver.get_tuple(config)
            initial: State | None = None if existing else {"run_id": run_id}
            state = graph.invoke(initial, config)
        current = {str(item["id"]): item for item in self.reader.evidence(self.actor)}
        refs = state.get("evidence_ids", [])
        public_evidence = [current[key] for key in refs if key in current]
        answer = state["answer"]
        result = {
            "run_id": run_id,
            "message_id": message_id,
            "thread_id": self.store.thread_id,
            "answer": answer,
            "public_answer": state.get("public_answer", answer)
            if state["mode"] in ("generated", "evidence_fallback")
            else "",
            "intent": state["intent"],
            "funnel_stage": state["stage"],
            "mode": state["mode"],
            "simulated": any(item["simulated"] for item in public_evidence),
            "disclosure": "演示场景：机构、供给与价格为虚构；模拟科普复核不代表真实医学批准"
            if any(item["simulated"] for item in public_evidence)
            else "",
            "evidence_ids": refs,
            "evidence": [
                {
                    "id": str(item["id"]),
                    "title": item["title"],
                    "source": item["source"],
                    "version": item["version"],
                    "simulated": item["simulated"],
                    "review_scope": item.get("review_scope") or "standard",
                }
                for item in public_evidence
            ],
            "handoff_reason": state.get("reason", ""),
            "handoff": None,
            "action": {"type": "visit_interest", "submitted": False}
            if state["intent"] == "visit_interest"
            else None,
        }
        compressed = self.memory_snapshot(plan, cast(State, state), message_id)
        result["project_ids"] = (
            [topics.projects[key]["id"] for key in keys]
            if keys
            and state["mode"] in ("generated", "evidence_fallback")
            and not state.get("reason")
            else self.catalog.related(self.actor, policy["question"], refs)
            if state["mode"] in ("generated", "evidence_fallback") and not state.get("reason")
            else []
        )
        return self.fresh_result(
            self.store.finish(
                run_id,
                lease,
                result,
                compressed,
                not bool(policy["reason"]) and policy["intent"] not in ("clarify", "support"),
            )
        )
