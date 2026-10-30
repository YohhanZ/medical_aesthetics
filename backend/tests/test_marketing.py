"""Isolated PostgreSQL integration and mocked supplier contracts; never spend real credits."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import create_app
from app.config import Settings
from app.db import transaction
from app.marketing_worker import MarketingWorker, MediaError, MediaGateway
from app.seed import OTHER_STORE, STORE
from tests.conftest import staff_headers, visitor_headers


@pytest.fixture
def configured(settings: Settings, tmp_path: Path) -> Settings:
    return settings.model_copy(
        update={
            "marketing_image_api_key": SecretStr("synthetic-image-key"),
            "marketing_video_api_key": SecretStr("synthetic-video-key"),
            "marketing_video_enabled": True,
            "marketing_video_workspace_id": "llm-synthetic",
            "marketing_media_root": str(tmp_path),
        }
    )


def body(kind: str = "image") -> dict[str, Any]:
    return {
        "request_key": str(uuid4()),
        "kind": kind,
        "title": "日常护理宣传",
        "prompt": "自然光的美容护理咨询空间，成年顾客与顾问交流",
        "caption": "本地文案不出站",
        "aspect": "portrait",
        "video_cost_acknowledged": kind == "video",
    }


BASE = f"/api/stores/{STORE}/marketing"


def test_disabled_provider_and_staff_scope(client: TestClient) -> None:
    author = staff_headers(client)
    options = client.get(BASE + "/options", headers=author)
    assert options.status_code == 200 and options.json()["image_ready"] is False
    assert options.json()["video_model"] == "wan3.0-video"
    assert options.json()["video_workspace_required"] is True
    assert "api_key" not in json.dumps(options.json())
    assert client.post(BASE + "/jobs", headers=author, json=body()).status_code == 409
    assert client.post(BASE + "/jobs", headers=author, json=body("video")).status_code == 409
    operator = staff_headers(client, "demo-operator")
    assert client.get(BASE + "/jobs", headers=operator).status_code == 403
    visitor_headers(client)
    assert client.get(BASE + "/jobs").status_code == 401
    assert client.get(BASE.replace(STORE, OTHER_STORE) + "/jobs", headers=author).status_code == 403


def test_wan3_missing_workspace_is_not_ready(configured: Settings) -> None:
    incomplete = configured.model_copy(update={"marketing_video_workspace_id": ""})
    with TestClient(create_app(incomplete)) as client:
        auth = staff_headers(client)
        options = client.get(BASE + "/options", headers=auth).json()
        assert options["video_ready"] is False and options["video_workspace_required"] is True
        assert client.post(BASE + "/jobs", headers=auth, json=body("video")).status_code == 409


def test_idempotency_daily_limit_and_video_confirmation(configured: Settings) -> None:
    cfg = configured.model_copy(update={"marketing_daily_limit": 1})
    with TestClient(create_app(cfg)) as client:
        auth = staff_headers(client)
        data = body()
        first = client.post(BASE + "/jobs", headers=auth, json=data)
        assert first.status_code == 201, first.text
        job = first.json()
        assert job["state"] == "queued" and job["simulated"]
        assert client.post(BASE + "/jobs", headers=auth, json=data).json()["id"] == job["id"]
        assert (
            client.post(
                BASE + "/jobs", headers=auth, json={**data, "prompt": "不同的宣传画面描述"}
            ).status_code
            == 409
        )
        assert client.post(BASE + "/jobs", headers=auth, json=body()).status_code == 429
        assert client.post(BASE + f"/jobs/{job['id']}/cancel", headers=auth).status_code == 200
        assert client.get(BASE + "/jobs", headers=auth).json()["items"][0]["state"] == "cancelled"
        assert client.post(BASE + f"/jobs/{job['id']}/cancel", headers=auth).status_code == 409
    with TestClient(create_app(configured)) as client:
        auth = staff_headers(client)
        data = {**body("video"), "video_cost_acknowledged": False}
        assert client.post(BASE + "/jobs", headers=auth, json=data).status_code == 422
        assert (
            client.post(
                BASE + "/jobs", headers=auth, json={**body(), "project_id": str(uuid4())}
            ).status_code
            == 409
        )


class FakeMedia(MediaGateway):
    def __init__(self, settings: Settings):
        super().__init__(
            settings, httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
        )
        self.submissions = 0
        self.polls = 0
        self.poll_models: list[str] = []
        self.unknown = False
        self.task = str(uuid4())

    def submit(self, row: dict[str, Any]) -> dict[str, str]:
        self.submissions += 1
        if self.unknown:
            raise MediaError("submission_unknown", True)
        return (
            {"url": "https://cdn.siliconflow.cn/test.png"}
            if row["kind"] == "image"
            else {"task": self.task}
        )

    def poll(self, task: str, model: str = "wan2.2-t2v-plus") -> dict[str, str]:
        assert task == self.task
        self.polls += 1
        self.poll_models.append(model)
        return (
            {}
            if self.polls == 1
            else {"url": "https://dashscope-result-bj.oss-accelerate.aliyuncs.com/test.mp4"}
        )

    def download(self, url: str, job: str, kind: str) -> tuple[str, str, int]:
        name = job + (".png" if kind == "image" else ".mp4")
        path = Path(self.settings.marketing_media_root) / name
        path.write_bytes(b"synthetic-asset")
        return name, "image/png" if kind == "image" else "video/mp4", path.stat().st_size


def test_image_worker_persists_asset_and_authenticates_download(configured: Settings) -> None:
    gateway = FakeMedia(configured)
    with TestClient(create_app(configured)) as client:
        auth = staff_headers(client)
        job = client.post(BASE + "/jobs", headers=auth, json=body()).json()
        assert MarketingWorker(configured, gateway).run_once()["status"] == "succeeded"
        result = client.get(BASE + f"/jobs/{job['id']}", headers=auth).json()
        assert result["state"] == "succeeded" and result["can_reconcile"]
        assert "provider_asset_url" not in result and "asset_name" not in result
        assert gateway.submissions == 1
        response = client.get(BASE + f"/jobs/{job['id']}/asset", headers=auth)
        assert response.status_code == 200 and response.content == b"synthetic-asset"
        assert response.headers["content-type"] == "image/png"
        assert client.get(BASE + f"/jobs/{job['id']}/asset").status_code == 401
        assert MarketingWorker(configured, gateway).run_once()["status"] == "idle"


def test_video_poll_survives_worker_restart_without_resubmission(configured: Settings) -> None:
    gateway = FakeMedia(configured)
    selected = configured.model_copy(update={"marketing_video_model": "wan3.0-video-prime"})
    with TestClient(create_app(selected)) as client:
        auth = staff_headers(client)
        job = client.post(BASE + "/jobs", headers=auth, json=body("video")).json()
        assert job["model"] == "wan3.0-video-prime"
        assert MarketingWorker(configured, gateway).run_once()["status"] == "running"
        with transaction(configured.database_url) as repo:
            repo.execute("UPDATE marketing_job SET available_at=now() WHERE id=%s", (job["id"],))
        assert MarketingWorker(configured, gateway).run_once()["status"] == "succeeded"
        assert gateway.submissions == 1 and gateway.polls == 2
        assert gateway.poll_models == ["wan3.0-video-prime", "wan3.0-video-prime"]
        result = client.get(BASE + f"/jobs/{job['id']}", headers=auth).json()
        assert result["state"] == "succeeded" and "synthetic-video-key" not in json.dumps(result)


def test_unknown_submission_never_automatically_retries(configured: Settings) -> None:
    gateway = FakeMedia(configured)
    gateway.unknown = True
    with TestClient(create_app(configured)) as client:
        auth = staff_headers(client)
        job = client.post(BASE + "/jobs", headers=auth, json=body()).json()
        worker = MarketingWorker(configured, gateway)
        worker.run_once()
        assert worker.run_once()["status"] == "idle"
        assert gateway.submissions == 1
        row = client.get(BASE + f"/jobs/{job['id']}", headers=auth).json()
        assert row["state"] == "unknown" and row["can_reconcile"] is False
        assert client.post(BASE + f"/jobs/{job['id']}/reconcile", headers=auth).status_code == 409


def test_asset_retry_reuses_provider_result(configured: Settings) -> None:
    class FlakyMedia(FakeMedia):
        downloads = 0

        def download(self, url: str, job: str, kind: str) -> tuple[str, str, int]:
            self.downloads += 1
            if self.downloads == 1:
                raise MediaError("asset_download_failed")
            return super().download(url, job, kind)

    gateway = FlakyMedia(configured)
    with TestClient(create_app(configured)) as client:
        auth = staff_headers(client)
        job = client.post(BASE + "/jobs", headers=auth, json=body()).json()
        worker = MarketingWorker(configured, gateway)
        assert worker.run_once()["status"] == "retry"
        with transaction(configured.database_url) as repo:
            repo.execute("UPDATE marketing_job SET available_at=now() WHERE id=%s", (job["id"],))
        assert worker.run_once()["status"] == "succeeded"
        assert gateway.submissions == 1 and gateway.downloads == 2


def test_expired_submit_lease_and_revoked_grant_do_not_call_provider(configured: Settings) -> None:
    gateway = FakeMedia(configured)
    with TestClient(create_app(configured)) as client:
        auth = staff_headers(client)
        job = client.post(BASE + "/jobs", headers=auth, json=body()).json()
        with transaction(configured.database_url) as repo:
            repo.execute(
                "UPDATE marketing_job SET state='submitting',"
                "lease_until=now()-interval '1 second' WHERE id=%s",
                (job["id"],),
            )
        assert MarketingWorker(configured, gateway).run_once()["status"] == "unknown"
        another = client.post(BASE + "/jobs", headers=auth, json=body()).json()
        with transaction(configured.database_url) as repo:
            repo.execute("DELETE FROM store_grant WHERE permission='knowledge_author'")
        assert MarketingWorker(configured, gateway).run_once()["status"] == "failed"
        assert gateway.submissions == 0
        assert client.get(BASE + f"/jobs/{another['id']}", headers=auth).status_code == 403


def test_provider_contracts_keep_caption_local_and_video_watermark(configured: Settings) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "output": {
                        "task_status": "SUCCEEDED",
                        "video_url": "https://test.aliyuncs.com/a.mp4",
                    }
                },
            )
        if "siliconflow" in request.url.host:
            return httpx.Response(
                200, json={"images": [{"url": "https://cdn.siliconflow.cn/a.png"}]}
            )
        return httpx.Response(200, json={"output": {"task_id": str(uuid4())}})

    gateway = MediaGateway(configured, httpx.Client(transport=httpx.MockTransport(handler)))
    data = {**body(), "model": "Kwai-Kolors/Kolors"}
    assert "url" in gateway.submit(data)
    assert "本地文案不出站" not in requests[0].content.decode()
    assert json.loads(requests[0].content)["image_size"] == "768x1024"
    data = {**body("video"), "model": "wan2.2-t2v-plus"}
    task = gateway.submit(data)["task"]
    assert json.loads(requests[1].content)["parameters"] == {
        "size": "480*832",
        "duration": 5,
        "watermark": True,
        "prompt_extend": False,
    }
    assert requests[1].headers["X-DashScope-Async"] == "enable"
    assert "url" in gateway.poll(task)
    quota_gateway = MediaGateway(
        configured,
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(403, json={"code": "AllocationQuota.FreeTierOnly"})
            )
        ),
    )
    with pytest.raises(MediaError) as error:
        quota_gateway.submit(data)
    assert error.value.code == "provider_quota"


def test_asset_url_guards(configured: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = MediaGateway(configured)
    for url in (
        "http://cdn.siliconflow.cn/a.png",
        "https://evil.test/a.png",
        "https://u:p@cdn.siliconflow.cn/a.png",
        "https://127.0.0.1/a.png",
    ):
        with pytest.raises(MediaError):
            gateway._asset_url(url)
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(MediaError):
        gateway._asset_url("https://cdn.siliconflow.cn/a.png")


def test_media_paths_never_escape_storage(configured: Settings) -> None:
    with TestClient(create_app(configured)) as client:
        auth = staff_headers(client)
        job = client.post(BASE + "/jobs", headers=auth, json=body()).json()
        with transaction(configured.database_url) as repo:
            repo.execute(
                "UPDATE marketing_job SET state='succeeded',asset_name='../../.env',"
                "asset_mime='image/png' WHERE id=%s",
                (job["id"],),
            )
        assert client.get(BASE + f"/jobs/{job['id']}/asset", headers=auth).status_code == 404


def test_asset_download_checks_format_size_and_never_sends_credentials(
    configured: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = httpx.Client
    gateway = MediaGateway(configured)
    monkeypatch.setattr(gateway, "_asset_url", lambda _: None)
    mode = "png"

    def respond(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers and "cookie" not in request.headers
        if mode == "redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        if mode == "oversize":
            return httpx.Response(200, content=b"a" * (1024 * 1024 + 1))
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nsynthetic-test-image")

    monkeypatch.setattr(
        "app.marketing_worker.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    name, mime, size = gateway.download("https://cdn.siliconflow.cn/a.png", str(uuid4()), "image")
    assert mime == "image/png" and size > 8
    assert (Path(configured.marketing_media_root) / name).is_file()
    mode = "redirect"
    with pytest.raises(MediaError):
        gateway.download("https://cdn.siliconflow.cn/a.png", str(uuid4()), "image")
    mode = "oversize"
    gateway.settings = configured.model_copy(update={"marketing_max_asset_mb": 1})
    with pytest.raises(MediaError) as error:
        gateway.download("https://cdn.siliconflow.cn/a.png", str(uuid4()), "image")
    assert error.value.code == "asset_too_large"
    assert not list(Path(configured.marketing_media_root).glob("*.part"))
