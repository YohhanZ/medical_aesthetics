import json

import httpx
import pytest

from app.config import Settings
from app.model_gateway import CircuitBreaker, GatewayError, QwenEmbeddingGateway, fingerprint


def config(text: str) -> Settings:
    return Settings(
        database_url="postgresql://unused",
        environment="test",
        model_api_key="test-only-not-a-real-key",
        model_export_hashes=[fingerprint(text)],
    )


@pytest.mark.parametrize(
    "url",
    [
        "dashscope.aliyuncs.com",
        "https://dashscope.aliyuncs.com/",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/",
    ],
)
def test_llm_environment_aliases_normalize_url_and_hide_key(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("LLM_MODEL", "qwen3.7-plus")
    monkeypatch.setenv("LLM_API_KEY", "synthetic-alias-key")
    monkeypatch.setenv("LLM_URL", url)
    monkeypatch.setenv("MA_MODEL_API_KEY", "synthetic-old-key")
    settings = Settings(_env_file=None, database_url="postgresql://unused")
    assert settings.model_api_key.get_secret_value() == "synthetic-alias-key"
    assert settings.chat_model == "qwen3.7-plus"
    assert settings.model_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings.embedding_model == "text-embedding-v4"
    assert "synthetic-alias-key" not in repr(settings)


@pytest.mark.parametrize("url", ["http://dashscope.aliyuncs.com", "https://untrusted.example/v1"])
def test_llm_url_cannot_redirect_credentials(url: str) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="postgresql://unused", model_base_url=url)


def test_payload_redacts_contacts_and_matches_vendor_contract() -> None:
    question = "合成问题：请联系13800138000 邮箱sample@example.test 微信:demo_contact"
    requests: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [1.0] * 256}]})

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        gateway = QwenEmbeddingGateway(config(question), client)
        assert len(gateway.embed(question)) == 256
    payload = json.loads(requests[0].content)
    assert payload["dimensions"] == 256 and payload["model"] == "text-embedding-v4"
    assert "13800138000" not in str(payload) and "sample@example.test" not in str(payload)
    assert "demo_contact" not in str(payload)
    assert set(payload) == {"model", "input", "dimensions"}


def test_unauthorized_export_never_calls_provider() -> None:
    called: list[bool] = []

    def serve(request: httpx.Request) -> httpx.Response:
        called.append(True)
        return httpx.Response(500)

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        with pytest.raises(GatewayError) as failure:
            QwenEmbeddingGateway(config("固定合成问题"), client).embed("另一条资料")
        assert failure.value.code == "export_not_authorized"
    assert not called


@pytest.mark.parametrize("status,count", [(401, 1), (400, 1), (429, 2), (503, 2)])
def test_bounded_retry_does_not_echo_provider_body(status: int, count: int) -> None:
    requests: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, text="SENSITIVE-provider-body")

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        with pytest.raises(GatewayError) as failure:
            QwenEmbeddingGateway(config("合成"), client, sleep=lambda _: None).embed("合成")
        assert failure.value.code == "model_http_failure"
        assert failure.value.status == status
    assert len(requests) == count


@pytest.mark.parametrize("values", [[1.0] * 255, [float("inf")] * 256, [True] * 256, [0.0] * 256])
def test_invalid_vectors_rejected(values: list[float]) -> None:
    # Content is built directly to allow malformed/non-finite vendor response simulation.
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=json.dumps({"data": [{"embedding": values}]}).encode()
            )
        )
    ) as client:
        with pytest.raises(GatewayError) as failure:
            QwenEmbeddingGateway(config("合成"), client).embed("合成")
    assert failure.value.code == "invalid_model_response"


def test_breaker_open_half_open_single_probe_and_recovery() -> None:
    moment = [100.0]
    breaker = CircuitBreaker(lambda: moment[0])
    for _ in range(10):
        breaker.enter()
        breaker.finish(False)
    with pytest.raises(GatewayError):
        breaker.enter()
    moment[0] += 31
    breaker.enter()
    with pytest.raises(GatewayError):
        breaker.enter()
    breaker.finish(True)
    breaker.enter()


def test_transient_retry_recovers() -> None:
    calls: list[bool] = []

    def serve(request: httpx.Request) -> httpx.Response:
        calls.append(True)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": [{"embedding": [1.0] * 256}]})

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        vector = QwenEmbeddingGateway(config("合成"), client, sleep=lambda _: None).embed("合成")
    assert len(calls) == 2 and len(vector) == 256


def test_chat_probe_is_gated_and_has_bounded_nonstreaming_payload() -> None:
    requests: list[httpx.Request] = []

    def serve(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "连接成功"}}]})

    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        gateway = QwenEmbeddingGateway(config("固定合成检查"), client)
        assert gateway.probe_chat("固定合成检查") == {
            "status": "connected",
            "model": "qwen3.7-plus",
        }
        with pytest.raises(GatewayError) as failure:
            gateway.probe_chat("未授权内容")
        assert failure.value.code == "export_not_authorized"
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert requests[0].url.path.endswith("/chat/completions")
    assert payload["stream"] is False and payload["enable_thinking"] is False
    assert payload["max_tokens"] == 32


def test_invalid_chat_probe_response_counts_as_breaker_failure() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    ) as client:
        gateway = QwenEmbeddingGateway(config("固定合成检查"), client)
        with pytest.raises(GatewayError) as failure:
            gateway.probe_chat("固定合成检查")
        assert failure.value.code == "invalid_model_response"
        assert gateway.breaker.results[-1][1] is False
