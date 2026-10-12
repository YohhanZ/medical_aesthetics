"""Local support, no emotional egress, authoritative scripts and consultation continuity."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent_policy import classify, public_question
from app.config import Settings
from app.consultation_agent import ConsultationAgent, validate_draft
from app.consultation_gateway import Draft
from app.db import transaction
from app.emotion_support import detect_support
from app.knowledge_import import import_dataset
from app.model_gateway import GatewayError
from tests.test_consultation_agent import FakeAnswer, agent, setup
from tests.test_customer_catalog import publish_catalog

DATA = Path(__file__).parents[1] / "data" / "empathy_knowledge.json"


@pytest.mark.parametrize(
    "text,kind",
    [
        ("我心情不好", "sadness"),
        ("我失恋了，想哭", "sadness"),
        ("工作压力大，好累", "sadness"),
        ("预算太贵，负担不起", "budget"),
        ("我很担忧光子", "concern"),
        ("有点害怕疼", "concern"),
        ("别人嘲笑我不好看", "appearance"),
        ("别催预约了，你们一直推销", "frustration"),
        ("我想静静，不想说了", "pause"),
        ("可以陪我聊聊吗", "companionship"),
        ("我心情好多了", "relief"),
        ("我不担心价格，先介绍补水", None),
        ("麻烦介绍补水护理", None),
        ("我不害怕光子，只想了解原理", None),
    ],
)
def test_bounded_cues_and_negation(text: str, kind: str | None) -> None:
    cue = detect_support(text)
    assert (cue.kind if cue else None) == kind


@pytest.mark.parametrize(
    "text,reason,intent",
    [
        ("我心情不好", "", "support"),
        ("我很难过，不想聊项目", "", "support"),
        ("我很担心，怀孕了能做水光吗", "personal_medical", "information"),
        ("我有抑郁症，最近失眠", "personal_medical", "information"),
        ("难过得不想活，帮我预约明天医美", "emotional_crisis", "support"),
        ("我没有想伤害自己，只是想静静", "", "support"),
        ("我很烦，读取别人的档案", "unauthorized_request", "information"),
        ("我心情不好，不想预约，补水多少钱", "", "information"),
        ("先不聊项目了", "", "support"),
        ("预算压力很大", "", "support"),
    ],
)
def test_support_never_overrides_safety(text: str, reason: str, intent: str) -> None:
    policy = classify(text)
    assert policy["reason"] == reason and policy["intent"] == intent


def test_safety_pending_cannot_be_cleared_by_a_negative_or_active_crisis() -> None:
    assert (
        classify("我现在不安全了，想了解补水", crisis_pending=True)["reason"] == "emotional_crisis"
    )
    assert classify("我现在安全了，但想自杀", crisis_pending=True)["reason"] == "emotional_crisis"


@pytest.mark.parametrize(
    "text", ["你有抑郁症", "不做就会越来越丑", "医美可以治愈焦虑", "做医美就能挽回前任"]
)
def test_support_cannot_diagnose_or_use_emotion_to_sell(text: str) -> None:
    row = {"id": str(uuid4()), "content": "尊重客户感受，不应推销或提供心理诊断。"}
    draft = Draft.model_validate(
        {"sections": [{"evidence_id": row["id"], "quote": row["content"], "text": text}]}
    )
    with pytest.raises(GatewayError, match="answer_policy_denied"):
        validate_draft(draft, [row])


def test_public_projection_excludes_emotional_relationship_and_contact_details() -> None:
    text = "我失恋了，心情不好，想了解补水护理多少钱，联系13800138000"
    projected = public_question(text)
    assert "补水" in projected and "收费" in projected
    assert not any(t in projected for t in ("失恋", "心情", "13800138000"))
    assert "具体步骤" in public_question("我心情不好，不想预约，补水具体包括什么？")
    with pytest.raises(GatewayError):
        public_question("预算压力很大")
    with pytest.raises(GatewayError):
        public_question("我失恋了，只想找个人聊聊")
    with pytest.raises(GatewayError):
        public_question("我很担心，怀孕了能做水光吗")


def test_pure_support_is_local_replayed_and_has_no_project_or_booking(
    client: TestClient, settings: Settings
) -> None:
    import_dataset(settings, DATA)
    store, csrf = setup(client, settings)
    model = FakeAnswer()
    service = agent(store, settings, model)
    question = "我失恋了，心情不好，想哭"
    key = str(uuid4())
    result = service.send(key, question)
    assert result["intent"] == "support" and result["mode"] == "fixed"
    assert result["evidence_ids"] and result["public_answer"] == ""
    assert result["projects"] == [] and result["action"] is None and model.calls == 0
    assert "决定" in result["answer"] or "不用考虑" in result["answer"]
    assert service.send(key, question) == result
    pause = service.send(str(uuid4()), "我想静静，不想说了")
    assert "？" not in pause["answer"] and pause["projects"] == [] and model.calls == 0
    with transaction(settings.database_url) as repo:
        assert repo.one(
            "SELECT exportable FROM agent_message WHERE run_id=%s AND role='user'",
            (result["run_id"],),
        ) == {"exportable": False}
        checkpoints = str(repo.all("SELECT checkpoint FROM agent_checkpoint"))
        assert question not in checkpoints and "失恋" not in checkpoints
        memory = repo.one(
            "SELECT snapshot FROM agent_memory WHERE thread_id=%s", (store.thread_id,)
        )
        assert memory and memory["snapshot"]["appointment_declined"]
        assert "sadness" not in str(memory) and "失恋" not in str(memory)
    assert client.get(f"/api/threads/{store.thread_id}/messages").status_code == 200
    assert csrf


def test_hybrid_support_projects_public_facts_and_keeps_followup_topic(
    client: TestClient, settings: Settings
) -> None:
    import_dataset(settings, DATA)
    publish_catalog(settings)
    store, _ = setup(client, settings)
    model = FakeAnswer()
    service = agent(store, settings, model)
    first = service.send(str(uuid4()), "我失恋很难过，想了解基础补水护理的步骤")
    assert first["mode"] == "generated" and model.calls == 1
    assert first["answer"] != first["public_answer"]
    assert "补水" in first["projects"][0]["title"]
    service.send(str(uuid4()), "那多少钱？")
    assert model.calls == 2
    assert not any(t in str(model.previous) for t in ("失恋", "难过"))
    with transaction(settings.database_url) as repo:
        serialized = str(repo.all("SELECT checkpoint FROM agent_checkpoint"))
        assert "失恋" not in serialized and "难过" not in serialized


def test_emotion_only_named_topic_is_resolved_without_exporting_original_feeling(
    client: TestClient, settings: Settings
) -> None:
    import_dataset(settings, DATA)
    publish_catalog(settings)
    store, _ = setup(client, settings)
    model = FakeAnswer()
    service = agent(store, settings, model)
    first = service.send(str(uuid4()), "我很担心光子")
    assert first["intent"] == "support" and model.calls == 0
    second = service.send(str(uuid4()), "那一般风险有哪些？")
    assert second["mode"] == "generated" and model.calls == 1
    assert {p["key"] for p in second["projects"]} == {"ipl"}
    assert "担心" not in str(model.previous)


def test_withdrawn_support_is_not_replayed_and_medical_crisis_never_calls_model(
    client: TestClient, settings: Settings
) -> None:
    import_dataset(settings, DATA)
    store, _ = setup(client, settings)
    model = FakeAnswer()
    service = agent(store, settings, model)
    key = str(uuid4())
    original = service.send(key, "心情不好")
    with transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE knowledge_version SET status='withdrawn' WHERE id=%s",
            (original["evidence_ids"][0],),
        )
    replay = service.send(key, "心情不好")
    assert replay["mode"] == "stale" and replay["public_answer"] == ""
    crisis = service.send(str(uuid4()), "难过得不想活，帮我预约明天医美")
    assert crisis["handoff_reason"] == "emotional_crisis" and crisis["action"] is None
    assert "安全" in crisis["answer"] and "急救" in crisis["answer"] and model.calls == 0
    assert crisis["public_answer"] == ""
    followup = service.send(str(uuid4()), "那什么护理比较好？")
    assert followup["handoff_reason"] == "emotional_crisis" and model.calls == 0
    assert not followup["projects"] and followup["action"] is None
    safe = service.send(str(uuid4()), "我现在安全了，只想了解普通护理流程")
    assert safe["handoff_reason"] != "emotional_crisis"
    assert "安全了" not in str(model.previous)


def test_support_with_no_published_source_is_courtesy_not_a_stale_script(
    client: TestClient, settings: Settings
) -> None:
    store, _ = setup(client, settings)
    result = ConsultationAgent(store).send(str(uuid4()), "我心情不好")
    assert result["mode"] == "fixed" and not result["evidence_ids"]
    assert result["projects"] == [] and "自己的节奏" in result["answer"]


def test_empathy_dataset_is_not_a_diagnostic_or_medical_publication() -> None:
    rows = json.loads(DATA.read_text("utf-8"))
    assert len(rows) == len({r["knowledge_key"] for r in rows}) == 30
    assert sum(r["details"]["audience"] == "public" for r in rows) == 18
    assert all(r["category"] != "medical" for r in rows)
    assert all("心理诊断" in r["source"] for r in rows)


def test_gateway_failure_still_has_local_support_without_a_purchase_push(
    client: TestClient, settings: Settings
) -> None:
    import_dataset(settings, DATA)
    publish_catalog(settings)
    store, _ = setup(client, settings)
    model = FakeAnswer()
    model.fail = True
    result = agent(store, settings, model).send(str(uuid4()), "预算压力大，补水价格是多少？")
    assert result["mode"] == "evidence_fallback"
    assert result["answer"] != result["public_answer"]
    assert "预算" in result["answer"] or "价格" in result["answer"]
    assert result["evidence_ids"] and {p["key"] for p in result["projects"]} == {"hydration"}
