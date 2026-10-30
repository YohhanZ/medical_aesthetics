"""Bounded media worker: submit once, poll known tasks, persist assets for authenticated access."""

import ipaddress
import signal
import socket
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from app.config import Settings
from app.db import transaction


class MediaError(Exception):
    def __init__(self, code: str, uncertain: bool = False):
        self.code, self.uncertain = code, uncertain


class MediaGateway:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=90, trust_env=False, follow_redirects=False)

    def _video_base_url(self, model: str) -> str:
        if model == "wan2.2-t2v-plus":
            return "https://dashscope.aliyuncs.com/api/v1"
        if model not in ("wan3.0-video", "wan3.0-video-prime"):
            raise MediaError("provider_model_unsupported")
        workspace = self.settings.marketing_video_workspace_id
        if not workspace:
            raise MediaError("provider_unconfigured")
        # Only a validated DNS label is configurable; keys cannot be sent to arbitrary hosts.
        return f"https://{workspace}.cn-beijing.maas.aliyuncs.com/api/v1"

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            try:
                error_body = response.json()
                provider_code = error_body.get("code", "") if isinstance(error_body, dict) else ""
            except ValueError:
                provider_code = ""
            code = {
                401: "provider_auth",
                403: "provider_auth",
                429: "provider_rate_limit",
                402: "provider_quota",
            }.get(response.status_code, "provider_rejected")
            if provider_code in (
                "AllocationQuota.FreeTierOnly",
                "QuotaExhausted",
                "InsufficientBalance",
                "Arrearage",
            ):
                code = "provider_quota"
            raise MediaError(code, response.status_code >= 500)
        try:
            data: dict[str, Any] = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (ValueError, TypeError):
            raise MediaError("provider_response_invalid", True) from None

    def submit(self, row: dict[str, Any]) -> dict[str, str]:
        # Only the visual brief is exported; no customer history or contacts are loaded.
        prompt = row["prompt"] + (
            "。自然真实的美容护理宣传场景，不展示治疗前后对比，不添加文字或价格，"
            "不呈现真实顾客或真实医生身份。"
        )
        try:
            if row["kind"] == "image":
                size = {"square": "1024x1024", "portrait": "768x1024", "landscape": "1024x1024"}[
                    row["aspect"]
                ]
                data = self._json(
                    self.client.post(
                        "https://api.siliconflow.cn/v1/images/generations",
                        headers={
                            "Authorization": "Bearer "
                            + self.settings.marketing_image_api_key.get_secret_value()
                        },
                        json={
                            "model": row["model"],
                            "prompt": prompt,
                            "image_size": size,
                            "num_inference_steps": 20,
                            "guidance_scale": 7.5,
                        },
                    )
                )
                return {"url": str(data["images"][0]["url"])}
            base_url = self._video_base_url(row["model"])
            parameters: dict[str, Any] = {
                "duration": 5,
                "watermark": True,
                "prompt_extend": False,
            }
            if row["model"] == "wan2.2-t2v-plus":
                parameters["size"] = {
                    "square": "624*624",
                    "portrait": "480*832",
                    "landscape": "832*480",
                }[row["aspect"]]
            else:
                parameters.update(
                    {
                        "resolution": "480P",
                        "ratio": {"square": "1:1", "portrait": "9:16", "landscape": "16:9"}[
                            row["aspect"]
                        ],
                        "audio": False,
                    }
                )
            data = self._json(
                self.client.post(
                    base_url + "/services/aigc/video-generation/video-synthesis",
                    headers={
                        "Authorization": "Bearer "
                        + self.settings.marketing_video_api_key.get_secret_value(),
                        "X-DashScope-Async": "enable",
                    },
                    json={
                        "model": row["model"],
                        "input": {"prompt": prompt},
                        "parameters": parameters,
                    },
                )
            )
            return {"task": str(UUID(data["output"]["task_id"]))}
        except httpx.HTTPError:
            # A POST timeout can occur after the provider accepted a billable task.
            raise MediaError("submission_unknown", True) from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise MediaError("provider_response_invalid", True) from None

    def poll(self, task: str, model: str = "wan2.2-t2v-plus") -> dict[str, str]:
        try:
            data = self._json(
                self.client.get(
                    self._video_base_url(model) + "/tasks/" + str(UUID(task)),
                    headers={
                        "Authorization": "Bearer "
                        + self.settings.marketing_video_api_key.get_secret_value()
                    },
                )
            )
            output = data["output"]
            state = output["task_status"]
            if state == "SUCCEEDED":
                return {"url": str(output["video_url"])}
            if state in ("FAILED", "CANCELED", "UNKNOWN"):
                raise MediaError("provider_task_failed")
            if state not in ("PENDING", "RUNNING"):
                raise MediaError("provider_response_invalid")
            return {}
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise MediaError("provider_poll_failed") from None

    def _asset_url(self, url: str) -> None:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            raise MediaError("asset_host_denied") from None
        host = parts.hostname or ""
        if (
            parts.scheme != "https"
            or parts.username
            or parts.password
            or port not in (None, 443)
            or not any(
                host == suffix or host.endswith("." + suffix)
                for suffix in self.settings.marketing_asset_hosts
            )
        ):
            raise MediaError("asset_host_denied")
        try:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise MediaError("asset_host_denied")
        except (OSError, ValueError):
            raise MediaError("asset_host_denied") from None

    def download(self, url: str, job: str, kind: str) -> tuple[str, str, int]:
        self._asset_url(url)
        root = Path(self.settings.marketing_media_root).resolve()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise MediaError("asset_download_failed") from None
        temporary = root / f"{UUID(job)}.part"
        total, header = 0, b""
        try:
            # No Authorization, cookies, redirects, or proxy credentials reach asset hosts.
            with httpx.Client(timeout=40, trust_env=False, follow_redirects=False) as downloader:
                with downloader.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise MediaError("asset_download_failed")
                    with temporary.open("wb") as target:
                        for chunk in response.iter_bytes(65536):
                            total += len(chunk)
                            if total > self.settings.marketing_max_asset_mb * 1024 * 1024:
                                raise MediaError("asset_too_large")
                            header = (header + chunk)[:32]
                            target.write(chunk)
            if kind == "video" and header[4:8] == b"ftyp":
                ext, mime = "mp4", "video/mp4"
            elif kind == "image" and header.startswith(b"\x89PNG\r\n\x1a\n"):
                ext, mime = "png", "image/png"
            elif kind == "image" and header.startswith(b"\xff\xd8\xff"):
                ext, mime = "jpg", "image/jpeg"
            elif kind == "image" and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
                ext, mime = "webp", "image/webp"
            else:
                raise MediaError("asset_format_invalid")
            filename = f"{UUID(job)}.{ext}"
            temporary.replace(root / filename)
            return filename, mime, total
        except (httpx.HTTPError, OSError):
            raise MediaError("asset_download_failed") from None
        finally:
            temporary.unlink(missing_ok=True)


class MarketingWorker:
    def __init__(self, settings: Settings, gateway: MediaGateway | None = None):
        self.settings = settings
        self.gateway = gateway or MediaGateway(settings)

    def run_once(self) -> dict[str, str]:
        # One media request at a time across all processes, with committed leases
        # in separate transactions. No provider call is retried as a new submission.
        with transaction(self.settings.database_url) as guard:
            lock = guard.one("SELECT pg_try_advisory_xact_lock(871230021) AS acquired")
            if not lock or not lock["acquired"]:
                return {"status": "idle"}
            return self._step()

    def _step(self) -> dict[str, str]:
        lease = str(uuid4())
        with transaction(self.settings.database_url) as repo:
            row = repo.one(
                "SELECT * FROM marketing_job WHERE state IN ('queued','submitting','running') "
                "AND available_at<=now() AND (lease_until IS NULL OR lease_until<now()) "
                "ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT 1"
            )
            if not row:
                return {"status": "idle"}
            if row["state"] == "submitting":
                repo.execute(
                    "UPDATE marketing_job SET state='unknown',error_code='submission_unknown',"
                    "updated_at=now(),lease_token=NULL,lease_until=NULL WHERE id=%s",
                    (row["id"],),
                )
                return {"status": "unknown"}
            if row["state"] == "running" and row["attempts"] >= 180:
                repo.execute(
                    "UPDATE marketing_job SET state='unknown',error_code='provider_poll_timeout',"
                    "lease_token=NULL,lease_until=NULL WHERE id=%s",
                    (row["id"],),
                )
                return {"status": "unknown"}
            allowed = repo.one(
                "SELECT g.staff_id FROM store_grant g JOIN staff u ON u.id=g.staff_id "
                "JOIN store s ON s.id=g.store_id JOIN tenant t ON t.id=g.tenant_id "
                "WHERE g.tenant_id=%s AND g.store_id=%s AND g.staff_id=%s "
                "AND g.permission='knowledge_author' AND u.active AND s.active "
                "AND (%s OR NOT (u.simulated OR s.simulated OR t.simulated))",
                (
                    row["tenant_id"],
                    row["store_id"],
                    row["staff_id"],
                    self.settings.allow_simulated_data,
                ),
            )
            if not allowed:
                repo.execute(
                    "UPDATE marketing_job SET state='failed',error_code='permission_revoked' "
                    "WHERE id=%s",
                    (row["id"],),
                )
                return {"status": "failed"}
            repo.execute(
                "UPDATE marketing_job SET state=CASE WHEN state='queued' "
                "THEN 'submitting' ELSE state END,"
                "lease_token=%s,lease_until=now()+interval '180 seconds',attempts=attempts+1,"
                "updated_at=now() WHERE id=%s",
                (lease, row["id"]),
            )
        try:
            ready = (
                bool(self.settings.marketing_image_api_key.get_secret_value())
                if row["kind"] == "image"
                else self.settings.marketing_video_enabled
                and bool(self.settings.marketing_video_api_key.get_secret_value())
            )
            if not ready:
                raise MediaError("provider_unconfigured")
            if row["state"] == "queued":
                result = self.gateway.submit(row)
                row["provider_task_id"] = result.get("task")
                row["provider_asset_url"] = result.get("url")
                # Commit provider identity before polling/downloading can fail.
                with transaction(self.settings.database_url) as repo:
                    repo.execute(
                        "UPDATE marketing_job SET provider_task_id=%s,provider_asset_url=%s,"
                        "state='running' WHERE id=%s AND lease_token=%s",
                        (row["provider_task_id"], row["provider_asset_url"], row["id"], lease),
                    )
                row["state"] = "running"
            if not row["provider_asset_url"] and row["provider_task_id"]:
                result = self.gateway.poll(row["provider_task_id"], row["model"])
                row["provider_asset_url"] = result.get("url")
                if row["provider_asset_url"]:
                    with transaction(self.settings.database_url) as repo:
                        repo.execute(
                            "UPDATE marketing_job SET provider_asset_url=%s WHERE id=%s "
                            "AND lease_token=%s",
                            (row["provider_asset_url"], row["id"], lease),
                        )
            if not row["provider_asset_url"]:
                self._finish(row, lease, "running", delay=8)
                return {"status": "running"}
            name, mime, size = self.gateway.download(
                row["provider_asset_url"], str(row["id"]), row["kind"]
            )
            with transaction(self.settings.database_url) as repo:
                repo.execute(
                    "UPDATE marketing_job SET state='succeeded',asset_name=%s,asset_mime=%s,"
                    "asset_bytes=%s,error_code=NULL,lease_token=NULL,lease_until=NULL,"
                    "updated_at=now() WHERE id=%s AND lease_token=%s",
                    (name, mime, size, row["id"], lease),
                )
            return {"status": "succeeded"}
        except MediaError as error:
            # GET/download retries preserve the original task ID and cannot create another video.
            retryable = error.code in (
                "provider_poll_failed",
                "asset_download_failed",
                "provider_rate_limit",
            )
            retry = row["state"] != "queued" and retryable and row["attempts"] < 30
            self._finish(
                row,
                lease,
                "running" if retry else ("unknown" if error.uncertain else "failed"),
                error.code,
                delay=15,
            )
            return {"status": "retry" if retry else "failed"}

    def _finish(
        self, row: dict[str, Any], lease: str, state: str, code: str | None = None, delay: int = 0
    ) -> None:
        with transaction(self.settings.database_url) as repo:
            repo.execute(
                "UPDATE marketing_job SET state=%s,error_code=%s,lease_token=NULL,"
                "lease_until=NULL,available_at=now()+%s*interval '1 second',updated_at=now() "
                "WHERE id=%s AND lease_token=%s",
                (state, code, delay, row["id"], lease),
            )


def main() -> None:
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    worker = MarketingWorker(Settings())
    try:
        while not stop.is_set():
            try:
                result = worker.run_once()
                stop.wait(3 if result["status"] == "idle" else 1)
            except Exception:
                # Provider responses, signed URLs, prompts and API keys never enter logs.
                print("marketing worker temporary failure", flush=True)
                stop.wait(5)
    finally:
        worker.gateway.client.close()


if __name__ == "__main__":
    main()
