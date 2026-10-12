from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent_policy import classify, public_question
from app.config import Settings
from app.consultation_agent import ConsultationAgent, validate_draft
from app.consultation_gateway import Draft
from app.db import transaction
from app.model_gateway import GatewayError
from app.retrieval import PostgresEvidenceReader, RetrievalService
from tests.test_consultation_agent import FakeAnswer, agent, setup
from tests.test_customer_catalog import publish_catalog


@pytest.mark.parametrize(
    "question,reason",
    [
        ("先介绍一下咨询流程，不给我定治疗方案", ""),
        ("我不需要你判断适合性，只想了解门店咨询流程", ""),
        ("我怀孕了，不给我定治疗方案，只问能做水光吗", "personal_medical"),
        ("我过敏，不需要你判断适合性，只问项目", "personal_medical"),
        ("光子嫩肤一般有哪些风险需要专业人员说明？", ""),
        ("那咨询之后是否一定要付款？", ""),
        ("帮我取消我的预约", "human_or_business"),
        ("我想现在付款", "human_or_business"),
    ],
)
def test_routing_public_negation_does_not_erase_personal_risk(question: str, reason: str) -> None:
    policy = classify(question)
    assert policy["reason"] == reason
    if not reason:
        assert policy["intent"] != "clarify"
    else:
        with pytest.raises(GatewayError):
            public_question(question)


def test_non_beauty_topic_is_rejected_even_in_historical_export() -> None:
    assert classify("换个话题，帮我写一个Python排序函数", True)["intent"] == "clarify"
    with pytest.raises(GatewayError):
        public_question("换个话题，帮我写一个Python排序函数")


@pytest.mark.parametrize(
    "text,allowed",
    [
        ("只有门店确认时间后才是已确认预约。", True),
        ("门店确认之后才算已确认预约。", True),
        ("已经为你预约好了。", False),
        ("您已确认预约。", False),
    ],
)
def test_conditional_process_is_not_a_completed_business_claim(text: str, allowed: bool) -> None:
    row = {"id": str(uuid4()), "content": "公开流程资料：只有门店确认时间后才是已确认预约。"}
    draft = Draft.model_validate(
        {"sections": [{"evidence_id": row["id"], "quote": row["content"], "text": text}]}
    )
    if allowed:
        assert validate_draft(draft, [row])[0] == text
    else:
        with pytest.raises(GatewayError):
            validate_draft(draft, [row])


def test_topic_survives_window_switches_and_new_thread_cannot_claim_it(
    client: TestClient, settings: Settings
) -> None:
    publish_catalog(settings)
    store, _ = setup(client, settings)
    service = agent(store, settings, FakeAnswer())
    service.send(str(uuid4()), "这段对话我只想了解补水护理")
    with transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE agent_memory SET snapshot=snapshot-'first_topic'-'active_topic' "
            "WHERE thread_id=%s",
            (store.thread_id,),
        )
    for _ in range(8):
        service.send(str(uuid4()), "你好")
    recall = service.send(str(uuid4()), "我们最初聊的是哪个护理方向？")
    assert recall["mode"] == "fixed" and "补水" in recall["answer"]
    service.send(str(uuid4()), "现在换个方向，了解清洁护理")
    recall = service.send(str(uuid4()), "现在回到一开始的护理方向，最初聊的是哪个？")
    assert "补水" in recall["answer"] and "清洁" not in recall["answer"]
    with transaction(settings.database_url) as repo:
        memory = repo.one(
            "SELECT snapshot FROM agent_memory WHERE thread_id=%s", (store.thread_id,)
        )
        assert memory and memory["snapshot"]["first_topic"]["keys"] == ["hydration"]
        assert memory["snapshot"]["active_topic"]["keys"] == ["cleansing"]
        assert "_topic_sources" not in memory["snapshot"]
    client.cookies.clear()
    fresh, _ = setup(client, settings)
    unknown = agent(fresh, settings, FakeAnswer()).send(str(uuid4()), "最初聊的是哪个护理方向？")
    assert "没有可确认" in unknown["answer"] and "补水" not in unknown["answer"]
    from psycopg.types.json import Jsonb

    with transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE agent_memory SET snapshot=%s WHERE thread_id=%s",
            (
                Jsonb({"first_topic": memory["snapshot"]["first_topic"]}),
                fresh.thread_id,
            ),
        )
    forged = agent(fresh, settings, FakeAnswer()).send(str(uuid4()), "最初聊的是哪个护理方向？")
    assert "没有可确认" in forged["answer"] and "补水" not in forged["answer"]


def test_fallback_cannot_use_last_comparison_project(
    client: TestClient, settings: Settings
) -> None:
    publish_catalog(settings)
    store, _ = setup(client, settings)
    reader = PostgresEvidenceReader(settings)
    current = reader.evidence(store.actor)
    hydration = next(r for r in current if r["knowledge_key"] == "catalog-hydration")
    cleansing = next(r for r in current if r["knowledge_key"] == "catalog-cleansing")

    class WrongOrder(RetrievalService):
        queries: list[str] = []

        def __init__(self) -> None:
            pass

        def search(self, actor: Any, question: str, limit: int = 5) -> dict[str, Any]:
            self.queries.append(question)
            return {"items": [cleansing, hydration], "method": "lexical"}

    model = FakeAnswer()
    model.fail = True
    retrieval = WrongOrder()
    service = ConsultationAgent(store, retrieval, model)
    service.send(str(uuid4()), "想了解基础补水护理")
    comparison = service.send(str(uuid4()), "那它和清洁护理有什么区别？")
    assert {p["key"] for p in comparison["projects"]} == {"hydration", "cleansing"}
    key = str(uuid4())
    answer = service.send(key, "刚才说的补水，具体服务内容能再说明一下吗？")
    assert answer["mode"] == "evidence_fallback"
    assert "基础补水护理" in answer["answer"] and "清洁护理" not in answer["answer"]
    assert answer["evidence_ids"] == [str(hydration["id"])]
    assert [p["key"] for p in answer["projects"]] == ["hydration"]
    assert "清洁" not in retrieval.queries[-1]
    assert service.send(key, "刚才说的补水，具体服务内容能再说明一下吗？") == answer


def test_risk_followup_stays_local_and_public_flow_can_resume(
    client: TestClient, settings: Settings
) -> None:
    store, _ = setup(client, settings)
    model = FakeAnswer()
    service = agent(store, settings, model)
    service.send(str(uuid4()), "我怀孕了，可以做水光吗？")
    service.send(str(uuid4()), "你好")
    followup = service.send(str(uuid4()), "那换成光子能做吗？")
    assert followup["handoff_reason"] == "personal_medical" and model.calls == 0
    short = service.send(str(uuid4()), "那这个呢？")
    assert short["handoff_reason"] == "personal_medical" and model.calls == 0
    resumed = service.send(str(uuid4()), "我不需要你判断适合性，只想了解门店咨询流程")
    assert resumed["mode"] == "generated" and model.calls == 1
    assert all("怀孕" not in question and "能做" not in question for question in model.previous)
    with transaction(settings.database_url) as repo:
        snapshot = repo.one("SELECT snapshot FROM agent_memory")["snapshot"]
        assert snapshot["medical_pending"] is False and snapshot["contains_medical_facts"] is False
        assert "怀孕" not in str(repo.all("SELECT checkpoint FROM agent_checkpoint"))


def test_previous_public_answers_are_source_checked_and_withdrawal_excludes_them(
    client: TestClient, settings: Settings
) -> None:
    store, _ = setup(client, settings)

    class Capture(FakeAnswer):
        dialogue: list[dict[str, Any]] = []

        def answer(
            self,
            question: str,
            previous: list[str],
            evidence: list[dict[str, Any]],
            dialogue: list[dict[str, Any]] | None = None,
        ) -> Draft:
            self.dialogue = dialogue or []
            return super().answer(question, previous, evidence, dialogue)

    model = Capture()
    service = agent(store, settings, model)
    first = service.send(str(uuid4()), "首次到店咨询流程是什么？")
    service.send(str(uuid4()), "你刚才提到的第二个步骤，能展开吗？")
    assert model.dialogue and model.dialogue[0]["answer"] == first["answer"]
    with transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE knowledge_version SET status='withdrawn' WHERE id=ANY(%s::uuid[])",
            (first["evidence_ids"],),
        )
    service.send(str(uuid4()), "请用一句话总结我们刚才说的流程")
    assert all(not set(d["evidence_ids"]) & set(first["evidence_ids"]) for d in model.dialogue)


def test_invalid_quote_gets_one_checked_retry_without_returning_bad_draft(
    client: TestClient, settings: Settings
) -> None:
    store, _ = setup(client, settings)

    class BadThenGood(FakeAnswer):
        def answer(self, *args: Any, **kwargs: Any) -> Draft:
            draft = super().answer(*args, **kwargs)
            if self.calls == 1:
                draft.sections[0].quote = "这是一段不属于当前证据的错误引用"
                draft.sections[0].text = "不应返回的错误草稿"
            return draft

    model = BadThenGood()
    answer = agent(store, settings, model).send(str(uuid4()), "到店咨询流程是什么？")
    assert model.calls == 2 and answer["mode"] == "generated"
    assert "错误草稿" not in answer["answer"]
    trace = ConsultationAgent(store).get_run(answer["run_id"])["trace"]
    assert any(node["node"] == "model_retry" for node in trace)


def test_api_domain_switch_after_public_reply_is_local_and_persistent(
    client: TestClient, settings: Settings
) -> None:
    publish_catalog(settings)
    store, csrf = setup(client, settings)
    model = FakeAnswer()
    client.app.state.agent_factory = lambda selected: agent(selected, settings, model)
    url = f"/api/threads/{store.thread_id}/messages"
    first = client.post(
        url, headers=csrf, json={"message_id": str(uuid4()), "question": "想了解基础补水护理"}
    )
    assert first.status_code == 200
    body = {"message_id": str(uuid4()), "question": "换个话题，帮我写一个Python排序函数"}
    response = client.post(url, headers=csrf, json=body)
    assert response.status_code == 200 and response.json()["mode"] == "fixed"
    assert model.calls == 1
    assert client.post(url, headers=csrf, json=body).json() == response.json()
    with transaction(settings.database_url) as repo:
        assert repo.one(
            "SELECT exportable FROM agent_message WHERE run_id=%s AND role='user'",
            (response.json()["run_id"],),
        ) == {"exportable": False}
