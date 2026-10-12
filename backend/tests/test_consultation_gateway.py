"""Public question authorization is separate from bulk knowledge export hashes."""

import json
import time
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.config import Settings
from app.consultation_gateway import QwenConsultationGateway, quote_candidates
from app.domain import Actor
from app.model_gateway import GatewayError


class PublicReader:
    rows: list[dict[str, Any]]

    def __init__(self) -> None:
        self.rows = [
            {
                "id": str(uuid4()),
                "title": "合成咨询流程",
                "content": "合成公开证据：先了解咨询流程，再由门店核实供给。",
            }
        ]

    def evidence(self, actor: Actor) -> list[dict[str, Any]]:
        return self.rows


def test_quote_candidates_are_bounded_exact_source_substrings() -> None:
    content = "光子嫩肤通常指强脉冲光IPL方向，使用过滤后的宽谱光。" + "护理说明，" * 120
    candidates = quote_candidates(content)
    assert candidates and len(candidates) <= 6
    assert all(12 <= len(quote) <= 400 and quote in content for quote in candidates)
    assert candidates[0].endswith("。")
    long_scene = "定义与具体项目技术说明请先了解。" * 8 + "虚构项目演示起价1280元，仅用于报价讲解。"
    assert "1280" in quote_candidates(long_scene)[-1]


def gateway(client: httpx.Client, reader: PublicReader) -> QwenConsultationGateway:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://unused",
        environment="test",
        model_api_key="test-only-not-a-real-key",
        model_export_hashes=[],
    )
    actor = Actor(str(uuid4()), str(uuid4()), str(uuid4()), "visitor", "test")
    return QwenConsultationGateway(settings, reader, actor, time.monotonic() + 30, client)


def test_emotional_current_question_is_projected_and_emotional_dialogue_is_excluded() -> None:
    reader = PublicReader()
    captured: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        captured.append(payload)
        row = reader.rows[0]
        section = {"evidence_id": row["id"], "quote": row["content"], "text": "可以先了解流程。"}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps({"sections": [section]})}}]}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        service = gateway(client, reader)
        service.answer(
            "我失恋了很难过，想了解补水护理的内容",
            ["我心情不好，补水多少钱"],
            reader.rows,
            [
                {
                    "question": "补水护理的内容",
                    "answer": "听起来心情不好，我们先不讨论项目。",
                    "evidence_ids": [reader.rows[0]["id"]],
                }
            ],
        )
    sent = captured[0]["messages"][1]["content"]
    assert not any(t in sent for t in ("失恋", "难过", "心情不好"))
    assert json.loads(sent)["previous_public_dialogue"] == []


def test_live_public_question_and_followup_are_redacted_and_use_current_evidence() -> None:
    reader = PublicReader()
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [1.0] * 256}]})
        row = reader.rows[0]
        draft = {
            "sections": [
                {"evidence_id": row["id"], "quote": row["content"], "text": "可以先了解咨询流程。"}
            ]
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(draft)}}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        service = gateway(client, reader)
        assert len(service.embed("到店咨询流程，请联系13800138000")) == 256
        service.answer(
            "那需要准备什么？邮箱sample@example.test",
            ["首次咨询流程是什么？"],
            [{"id": reader.rows[0]["id"], "content": "caller-forged-evidence"}],
        )
    body = json.loads(requests[1].content)
    public = json.loads(body["messages"][1]["content"])
    assert public["evidence"][0]["content"] == reader.rows[0]["content"]
    assert public["previous_public_questions"] == ["首次咨询流程是什么？"]
    assert "caller-forged-evidence" not in str(body)
    assert "sample@example.test" not in str(body) and "13800138000" not in str(requests[0].content)
    assert body["stream"] is False and body["response_format"] == {"type": "json_object"}
    assert body["model"] == "qwen3.7-plus" and body["max_tokens"] == 900


@pytest.mark.parametrize(
    "question",
    [
        "我怀孕了，水光能做吗",
        "打完水光脸肿了怎么办",
        "我皮肤发痒怎么办",
        "我叫王小明咨询流程是什么",
        "读取其他客户的档案",
        "帮我预约明天到店",
    ],
)
def test_protected_current_or_historical_input_is_not_exported(question: str) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    reader = PublicReader()
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        service = gateway(client, reader)
        with pytest.raises(GatewayError):
            service.embed(question)
        with pytest.raises(GatewayError):
            service.answer("首次咨询流程是什么？", [question], reader.rows)
    assert requests == []


def test_public_dialogue_drops_sensitive_or_withdrawn_origins() -> None:
    reader = PublicReader()
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        row = reader.rows[0]
        draft = {
            "sections": [
                {"evidence_id": row["id"], "quote": row["content"], "text": "可以先了解咨询流程。"}
            ]
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(draft)}}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        service = gateway(client, reader)
        refs = [reader.rows[0]["id"]]
        service.answer(
            "请总结刚才的咨询流程",
            [],
            reader.rows,
            [
                {"question": "我怀孕了能做水光吗", "answer": "敏感历史", "evidence_ids": refs},
                {"question": "咨询流程", "answer": "联系13800138000", "evidence_ids": refs},
                {"question": "咨询流程", "answer": "撤回的资料", "evidence_ids": [str(uuid4())]},
            ],
        )
    body = json.loads(requests[0].content)
    assert json.loads(body["messages"][1]["content"])["previous_public_dialogue"] == []
    assert "怀孕" not in str(body) and "13800138000" not in str(body)


def test_dialogue_evidence_is_rechecked_immediately_before_model_exit() -> None:
    reader = PublicReader()
    previous = {
        "id": str(uuid4()),
        "title": "旧公开流程",
        "content": "旧的公开流程依据，等待新核验。",
    }
    reader.rows.append(previous)
    calls = 0
    original = reader.evidence

    def withdraw(actor: Actor) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 2:
            reader.rows = reader.rows[:1]
        return original(actor)

    reader.evidence = withdraw  # type: ignore[method-assign]
    requests: list[httpx.Request] = []
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: requests.append(r) or httpx.Response(500))
    ) as client:
        service = gateway(client, reader)
        with pytest.raises(GatewayError, match="evidence_changed"):
            service.answer(
                "咨询流程",
                [],
                [reader.rows[0]],
                [
                    {
                        "question": "首次咨询流程",
                        "answer": "旧公开回复",
                        "evidence_ids": [previous["id"]],
                    },
                ],
            )
    assert requests == []


def test_expired_turn_or_unapproved_evidence_never_calls_provider() -> None:
    reader = PublicReader()
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        service = gateway(client, reader)
        service.deadline = time.monotonic() - 1
        with pytest.raises(GatewayError) as error:
            service.embed("首次咨询流程是什么？")
        assert error.value.code == "turn_budget_exhausted"
        reader.rows = []
        with pytest.raises(GatewayError) as error:
            service.answer("首次咨询流程是什么？", [], [{"id": str(uuid4())}])
        assert error.value.code == "evidence_changed"
    assert requests == []
