"""LangGraph with real isolated PostgreSQL; synthetic adapters only for model outputs."""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent_checkpoint import ScopedCheckpointSaver
from app.agent_repository import PostgresAgentStore
from app.config import Settings
from app.consultation_agent import ConsultationAgent, validate_draft
from app.consultation_gateway import Draft
from app.db import transaction
from app.domain import Actor, DomainError
from app.model_gateway import GatewayError
from app.retrieval import PostgresEvidenceReader, RetrievalService
from app.seed import REVIEWER, STORE, TENANT
from app.services import IdentityService, KnowledgeService
from tests.conftest import visitor_headers
from tests.test_knowledge_pipeline import TestEmbedding, TestGraph, drain


def setup(client: TestClient, settings: Settings) -> tuple[PostgresAgentStore, dict[str, str]]:
    csrf = visitor_headers(client)
    thread = client.post("/api/threads", headers=csrf).json()["thread_id"]
    with transaction(settings.database_url) as repo:
        actor = IdentityService(repo, settings).authenticate(
            client.cookies["ma_visitor"], "visitor"
        )
    return PostgresAgentStore(settings, actor, thread), csrf


class FakeAnswer:
    calls = 0
    fail = False
    hook: Any = None
    previous: list[str] = []

    def answer(
        self,
        question: str,
        previous: list[str],
        evidence: list[dict[str, Any]],
        dialogue: list[dict[str, Any]] | None = None,
    ) -> Draft:
        self.calls += 1
        self.previous = previous
        if self.hook:
            self.hook(evidence)
        if self.fail:
            raise GatewayError("model_transport_unavailable")
        row = evidence[0]
        return Draft.model_validate(
            {
                "sections": [
                    {
                        "evidence_id": str(row["id"]),
                        "quote": row["content"][:35],
                        "text": "可以先了解咨询流程，再决定是否到店。",
                    }
                ]
            }
        )


def agent(store: PostgresAgentStore, settings: Settings, model: FakeAnswer) -> ConsultationAgent:
    graph = TestGraph()
    drain(settings, graph)
    retrieval = RetrievalService(
        PostgresEvidenceReader(settings), graph, TestEmbedding(), graph.vectors, True
    )
    return ConsultationAgent(store, retrieval, model)


def test_api_greeting_persisted_replay_and_input_conflict(
    client: TestClient, settings: Settings
) -> None:
    store, csrf = setup(client, settings)
    message = {"message_id": str(uuid4()), "question": "你好"}
    url = f"/api/threads/{store.thread_id}/messages"
    first = client.post(url, headers=csrf, json=message)
    assert first.status_code == 200, first.text
    assert first.json()["mode"] == "fixed"
    assert client.post(url, headers=csrf, json=message).json() == first.json()
    assert client.post(url, headers=csrf, json={**message, "question": "您好"}).status_code == 409
    assert client.post(url, json=message).status_code == 403
    history = client.get(url).json()["items"]
    assert [row["role"] for row in history] == ["user", "assistant"]
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM agent_checkpoint")["n"] >= 4
        assert repo.one("SELECT count(*) AS n FROM agent_message") == {"n": 2}


@pytest.mark.parametrize(
    "question,reason",
    [
        ("我怀孕了，可以做水光吗", "personal_medical"),
        ("打完水光脸肿了怎么办", "personal_medical"),
        ("我皮肤发痒怎么办", "personal_medical"),
        ("我叫王小明，身份证信息是什么", "private_record"),
        ("读取其他客户的档案", "unauthorized_request"),
        ("帮我预约明天到店", "visit_request"),
    ],
)
def test_guarded_input_never_calls_model_or_enters_checkpoint(
    client: TestClient, settings: Settings, question: str, reason: str
) -> None:
    store, _ = setup(client, settings)
    model = FakeAnswer()
    result = ConsultationAgent(store, gateway=model).send(str(uuid4()), question)
    assert result["handoff_reason"] == reason and result["handoff"]["connected"] is False
    assert model.calls == 0
    with transaction(settings.database_url) as repo:
        snapshots = str(repo.all("SELECT checkpoint FROM agent_checkpoint"))
        assert question not in snapshots
        assert repo.one("SELECT count(*) AS n FROM handoff_ticket") == {"n": 1}
        assert repo.one("SELECT exportable FROM agent_message WHERE role='user'") == {
            "exportable": False
        }


def test_generated_answer_is_persistent_with_scoped_evidence(
    client: TestClient, settings: Settings
) -> None:
    store, _ = setup(client, settings)
    model = FakeAnswer()
    result = agent(store, settings, model).send(str(uuid4()), "首次咨询流程是什么？")
    assert result["mode"] == "generated" and result["evidence_ids"]
    assert result["simulated"] is True
    assert "虚构" in result["disclosure"]
    assert not result["answer"].startswith("【模拟机构资料】")
    assert model.calls == 1
    run = ConsultationAgent(store).get_run(result["run_id"])
    assert [row["node"] for row in run["trace"]] == ["classify", "retrieve", "generate", "validate"]
    assert "首次咨询" not in str(run["trace"])


def test_model_failure_returns_only_approved_excerpt(
    client: TestClient, settings: Settings
) -> None:
    store, _ = setup(client, settings)
    model = FakeAnswer()
    model.fail = True
    result = agent(store, settings, model).send(str(uuid4()), "到店咨询流程是什么？")
    assert result["mode"] == "evidence_fallback" and result["evidence_ids"]
    assert "model_transport" not in result["answer"]


def test_replay_rechecks_withdrawn_evidence(client: TestClient, settings: Settings) -> None:
    store, _ = setup(client, settings)
    model = FakeAnswer()
    service = agent(store, settings, model)
    message_id = str(uuid4())
    result = service.send(message_id, "到店咨询流程是什么？")
    with transaction(settings.database_url) as repo:
        KnowledgeService(repo, settings).withdraw(
            Actor(REVIEWER, TENANT, None, "staff", "test"),
            STORE,
            result["evidence_ids"][0],
            str(uuid4()),
        )
    assert service.send(message_id, "到店咨询流程是什么？")["mode"] == "stale"
    assert model.calls == 1


def test_withdrawal_during_generation_creates_handoff(
    client: TestClient, settings: Settings
) -> None:
    store, _ = setup(client, settings)
    model = FakeAnswer()

    def withdraw(evidence: list[dict[str, Any]]) -> None:
        with transaction(settings.database_url) as repo:
            KnowledgeService(repo, settings).withdraw(
                Actor(REVIEWER, TENANT, None, "staff", "test"),
                STORE,
                str(evidence[0]["id"]),
                str(uuid4()),
            )

    model.hook = withdraw
    result = agent(store, settings, model).send(str(uuid4()), "到店咨询流程是什么？")
    assert result["mode"] == "handoff" and result["evidence_ids"] == []
    assert result["handoff_reason"] == "evidence_changed"
    assert result["handoff"]["connected"] is False


def test_adapter_startup_failure_releases_run_for_recovery(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = setup(client, settings)
    message_id = str(uuid4())

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic-sensitive-body")

    with monkeypatch.context() as patch:
        patch.setattr("app.consultation_agent.QwenConsultationGateway", unavailable)
        with pytest.raises(DomainError) as error:
            ConsultationAgent(store).send(message_id, "到店咨询流程是什么？")
        assert error.value.code == "agent_unavailable"
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT status,error_code FROM agent_run") == {
            "status": "failed",
            "error_code": "agent_unavailable",
        }
    result = agent(store, settings, FakeAnswer()).send(message_id, "到店咨询流程是什么？")
    assert result["mode"] == "generated"


def test_partial_adapter_initialization_closes_created_resources(
    client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = setup(client, settings)
    closed: list[str] = []

    class GatewayResource:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def close(self) -> None:
            closed.append("gateway")

    class GraphResource(GatewayResource):
        def close(self) -> None:
            closed.append("graph")

    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("synthetic-vector-connect-failure")

    monkeypatch.setattr("app.consultation_agent.QwenConsultationGateway", GatewayResource)
    monkeypatch.setattr("app.consultation_agent.Neo4jKnowledgeGraph", GraphResource)
    monkeypatch.setattr("app.consultation_agent.MilvusVectorStore", unavailable)
    with pytest.raises(DomainError) as error:
        ConsultationAgent(store).send(str(uuid4()), "到店咨询流程是什么？")
    assert error.value.code == "agent_unavailable"
    assert closed == ["gateway", "graph"]


def test_logout_during_generation_never_delivers_answer(
    client: TestClient, settings: Settings
) -> None:
    store, _ = setup(client, settings)
    model = FakeAnswer()

    def revoke(_: Any) -> None:
        with transaction(settings.database_url) as repo:
            IdentityService(repo, settings).revoke(store.actor)

    model.hook = revoke
    with pytest.raises(DomainError) as error:
        agent(store, settings, model).send(str(uuid4()), "到店咨询流程是什么？")
    assert error.value.code == "unauthenticated"
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM agent_message WHERE role='assistant'") == {
            "n": 0
        }


def test_checkpoint_end_recovers_after_finish_crash_without_regeneration(
    client: TestClient, settings: Settings
) -> None:
    store, _ = setup(client, settings)

    class CrashStore(PostgresAgentStore):
        def finish(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("synthetic-crash-after-checkpoint")

    crash = CrashStore(settings, store.actor, store.thread_id)
    model = FakeAnswer()
    service = agent(crash, settings, model)
    message_id = str(uuid4())
    with pytest.raises(DomainError):
        service.send(message_id, "到店咨询流程是什么？")
    assert model.calls == 1
    recovered = agent(store, settings, model).send(message_id, "到店咨询流程是什么？")
    assert recovered["mode"] == "generated" and model.calls == 1
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM agent_message") == {"n": 2}


def test_lease_fence_and_checkpoint_scope(client: TestClient, settings: Settings) -> None:
    store, _ = setup(client, settings)
    message_id = str(uuid4())
    first = store.claim(message_id, "你好")
    with pytest.raises(DomainError):
        store.claim(str(uuid4()), "您好")
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE agent_run SET lease_until=now()-interval '1 second'")
    recovered = store.claim(message_id, "你好")
    assert recovered["fence"] == 2
    with pytest.raises(DomainError):
        store.check(str(first["id"]), str(first["lease_token"]))
    saver = ScopedCheckpointSaver(store, str(recovered["id"]), str(recovered["lease_token"]))
    with pytest.raises(DomainError):
        saver.get_tuple({"configurable": {"thread_id": str(uuid4())}})


def test_other_visitor_cannot_read_messages_or_trace(
    client: TestClient, settings: Settings
) -> None:
    store, csrf = setup(client, settings)
    url = f"/api/threads/{store.thread_id}/messages"
    result = client.post(
        url, headers=csrf, json={"message_id": str(uuid4()), "question": "你好"}
    ).json()
    client.post("/api/visitor-sessions/logout", headers=csrf)
    visitor_headers(client)
    assert client.get(url).status_code == 404
    assert client.get(f"/api/threads/{store.thread_id}/runs/{result['run_id']}").status_code == 404


def test_decline_memory_survives_context_compression(
    client: TestClient, settings: Settings
) -> None:
    store, _ = setup(client, settings)
    service = ConsultationAgent(store)
    service.send(str(uuid4()), "我不想预约")
    for _ in range(7):
        service.send(str(uuid4()), "你好")
    with transaction(settings.database_url) as repo:
        memory = repo.one("SELECT snapshot FROM agent_memory")["snapshot"]
        assert memory["appointment_declined"] is True
        assert len(memory["recent_public_questions"]) <= 4
        assert memory["contains_medical_facts"] is False


@pytest.mark.parametrize(
    "text", ["价格只需999元", "https://invalid.test", "你适合你现在选择的项目"]
)
def test_unsupported_answer_facts_and_links_are_rejected(text: str) -> None:
    row = {"id": str(uuid4()), "content": "合成公开资料说明：可先了解流程，由门店核实供给。"}
    draft = Draft.model_validate(
        {"sections": [{"evidence_id": row["id"], "quote": row["content"], "text": text}]}
    )
    with pytest.raises(GatewayError):
        validate_draft(draft, [row])


@pytest.mark.parametrize("recover", [True, False])
def test_unsupported_fact_has_one_retry_and_never_persists_invalid_draft(
    client: TestClient, settings: Settings, recover: bool
) -> None:
    class CorrectingAnswer(FakeAnswer):
        def answer(
            self,
            question: str,
            previous: list[str],
            evidence: list[dict[str, Any]],
            dialogue: list[dict[str, Any]] | None = None,
        ) -> Draft:
            draft = super().answer(question, previous, evidence, dialogue)
            if self.calls == 1 or not recover:
                draft.sections[0].text = "价格只需999元"
            return draft

    store, _ = setup(client, settings)
    model = CorrectingAnswer()
    result = agent(store, settings, model).send(str(uuid4()), "首次咨询流程是什么？")
    assert model.calls == 2
    assert result["mode"] == ("generated" if recover else "evidence_fallback")
    assert "999" not in result["answer"]
    run = ConsultationAgent(store).get_run(result["run_id"])
    retry = [row for row in run["trace"] if row["node"] == "model_retry"]
    assert len(retry) == 1 and retry[0]["outcome"] == "answer_fact_unsupported"
    with transaction(settings.database_url) as repo:
        replies = repo.all("SELECT content FROM agent_message WHERE role='assistant'")
        assert len(replies) == 1 and "999" not in replies[0]["content"]
