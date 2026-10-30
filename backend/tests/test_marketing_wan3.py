"""Wan 3.0 supplier contracts use only synthetic credentials and mocked HTTP."""

import json
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.marketing_worker import MediaError, MediaGateway


def config(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql://synthetic@127.0.0.1:55434/ma_m1_test",
        "environment": "test",
        "booking_sms_provider": "disabled",
        "marketing_video_api_key": "synthetic-video-key",
        "marketing_video_enabled": True,
        "marketing_video_workspace_id": "llm-synthetic",
    }
    return Settings(_env_file=None, **(values | overrides))


@pytest.mark.parametrize("model", ["wan3.0-video", "wan3.0-video-prime"])
@pytest.mark.parametrize(
    "aspect,ratio", [("portrait", "9:16"), ("square", "1:1"), ("landscape", "16:9")]
)
def test_wan3_submit_and_poll_use_beijing_workspace(model: str, aspect: str, ratio: str) -> None:
    requests: list[httpx.Request] = []
    task = str(uuid4())

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "llm-synthetic.cn-beijing.maas.aliyuncs.com"
        assert request.headers["Authorization"] == "Bearer synthetic-video-key"
        if request.method == "POST":
            assert request.url.path == "/api/v1/services/aigc/video-generation/video-synthesis"
            return httpx.Response(200, json={"output": {"task_id": task}})
        assert request.url.path == f"/api/v1/tasks/{task}"
        return httpx.Response(
            200,
            json={
                "output": {
                    "task_status": "SUCCEEDED",
                    "video_url": "https://test.aliyuncs.com/synthetic.mp4",
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        # A queued job keeps its own model even when the current configuration differs.
        gateway = MediaGateway(config(), client)
        result = gateway.submit(
            {
                "kind": "video",
                "model": model,
                "aspect": aspect,
                "prompt": "自然光下的虚构美容护理宣传空间",
                "caption": "LOCAL-COPY-MUST-NOT-LEAVE",
                "title": "LOCAL-TITLE-MUST-NOT-LEAVE",
            }
        )
        assert result == {"task": task}
        payload = json.loads(requests[0].content)
        assert payload["model"] == model
        assert payload["parameters"] == {
            "resolution": "480P",
            "ratio": ratio,
            "duration": 5,
            "audio": False,
            "watermark": True,
            "prompt_extend": False,
        }
        assert set(payload["input"]) == {"prompt"}
        assert "LOCAL-" not in requests[0].content.decode()
        assert requests[0].headers["X-DashScope-Async"] == "enable"
        assert "url" in gateway.poll(result["task"], model)
        assert len(requests) == 2


def test_workspace_is_required_before_any_supplier_request() -> None:
    def unexpected(_: httpx.Request) -> httpx.Response:
        pytest.fail("missing workspace must never send a provider request")

    cfg = config(marketing_video_workspace_id="")
    assert not cfg.marketing_video_ready
    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        gateway = MediaGateway(cfg, client)
        with pytest.raises(MediaError) as error:
            gateway.submit(
                {"kind": "video", "model": "wan3.0-video", "prompt": "演示", "aspect": "square"}
            )
        assert error.value.code == "provider_unconfigured"


@pytest.mark.parametrize(
    "workspace", ["https://evil.test", "x.evil.test", "bad/name", "bad_name", "a" * 64, "-bad"]
)
def test_workspace_cannot_redirect_credentials(workspace: str) -> None:
    with pytest.raises(ValidationError):
        config(marketing_video_workspace_id=workspace)


def test_models_and_readiness_are_explicit() -> None:
    assert config().marketing_video_ready
    assert not config(marketing_video_enabled=False).marketing_video_ready
    assert not config(marketing_video_api_key="").marketing_video_ready
    assert config(
        marketing_video_model="wan2.2-t2v-plus", marketing_video_workspace_id=""
    ).marketing_video_ready
    with pytest.raises(ValidationError):
        config(marketing_video_model="arbitrary-model")


def test_legacy_jobs_keep_their_original_endpoint_and_request_shape() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "dashscope.aliyuncs.com"
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": str(uuid4())}})
        return httpx.Response(200, json={"output": {"task_status": "RUNNING"}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        gateway = MediaGateway(config(), client)
        task = gateway.submit(
            {"kind": "video", "model": "wan2.2-t2v-plus", "aspect": "portrait", "prompt": "演示"}
        )
        assert json.loads(requests[0].content)["parameters"]["size"] == "480*832"
        assert "resolution" not in json.loads(requests[0].content)["parameters"]
        assert gateway.poll(task["task"], "wan2.2-t2v-plus") == {}
