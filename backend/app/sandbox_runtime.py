"""Docker runtime supervisor. The worker gets no network, credentials or host mounts."""

import logging
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.agent_repository import PostgresAgentStore
from app.config import Settings
from app.consultation_agent import ConsultationAgent
from app.domain import DomainError
from app.model_gateway import GatewayError
from app.sandbox_broker import Broker
from app.sandbox_wire import MAX_BYTES, MAX_CALLS, MAX_FRAME, decode, encode


def resolve_image(settings: Settings) -> str:
    if not re.fullmatch(
        r"(?:sha256:[a-f0-9]{64}|[a-z0-9][a-z0-9_./:@-]{0,199})", settings.sandbox_image
    ):
        raise RuntimeError("Invalid sandbox image reference")
    try:
        result = subprocess.run(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                '{{.Id}} {{index .Config.Labels "medical.consultation.worker"}}',
                settings.sandbox_image,
            ],
            capture_output=True,
            timeout=10,
            check=True,
        )
        image, role = result.stdout.decode().strip().split()
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image) or role != "v1":
            raise ValueError("image")
        return image
    except (OSError, subprocess.SubprocessError, ValueError):
        # Never silently execute in the API process when isolation is unavailable.
        raise RuntimeError(
            "Build the fixed sandbox image and start Docker before API startup"
        ) from None


def command(settings: Settings, image: str, name: str) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "--interactive",
        "--pull=never",
        "--name",
        name,
        "--label",
        "medical.consultation.sandbox=1",
        "--network=none",
        "--read-only",
        "--user=65532:65532",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true",
        "--memory",
        f"{settings.sandbox_memory_mb}m",
        "--memory-swap",
        f"{settings.sandbox_memory_mb}m",
        "--cpus",
        str(settings.sandbox_cpus),
        "--pids-limit=64",
        "--init",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777",
        "--ulimit",
        "nofile=128:128",
        "--log-driver=none",
        image,
    ]


def remove_container(name: str) -> None:
    try:
        result = subprocess.run(
            ["docker", "rm", "--force", name], capture_output=True, timeout=5, check=False
        )
        if result.returncode and b"is already in progress" in result.stderr:
            # --rm can race our forced cleanup; confirm disappearance before reporting pending.
            for _ in range(3):
                check = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.Status}}", name],
                    capture_output=True,
                    timeout=1,
                    check=False,
                )
                if check.returncode and (
                    b"No such object" in check.stderr or b"No such container" in check.stderr
                ):
                    return
                time.sleep(0.05)
        if result.returncode and b"No such container" not in result.stderr:
            logging.getLogger(__name__).warning("Sandbox cleanup pending container=%s", name)
    except (OSError, subprocess.SubprocessError):
        # API startup/ops must reconcile labelled orphan containers after a daemon outage.
        logging.getLogger(__name__).warning("Sandbox cleanup pending container=%s", name)


class DockerRuntime:
    def __init__(self, settings: Settings, image: str | None = None) -> None:
        self.settings = settings
        self.image = image or resolve_image(settings)
        self.slots = threading.BoundedSemaphore(settings.sandbox_max_concurrency)

    def check_available(self) -> None:
        try:
            subprocess.run(
                ["docker", "image", "inspect", "--format", "{{.Id}}", self.image],
                check=True,
                capture_output=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            raise DomainError("sandbox_unavailable", 503) from None

    def execute(
        self, job: dict[str, Any], dispatch: Callable[[str, dict[str, Any]], Any]
    ) -> dict[str, Any]:
        if not self.slots.acquire(blocking=False):
            raise DomainError("sandbox_busy", 503)
        name = "ma-consultation-sandbox-" + uuid4().hex
        deadline = time.monotonic() + self.settings.sandbox_timeout
        done, expired = threading.Event(), threading.Event()
        process: subprocess.Popen[bytes] | None = None
        total, sequence = 0, 0
        mailbox: queue.Queue[bytes] = queue.Queue(maxsize=1)

        def watchdog() -> None:
            if not done.wait(max(0, deadline - time.monotonic())):
                expired.set()
                remove_container(name)

        watcher = threading.Thread(target=watchdog, daemon=True)
        watcher.start()
        try:
            process = subprocess.Popen(
                command(self.settings, self.image, name),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            assert process.stdin and process.stdout

            def read() -> None:
                assert process and process.stdout
                while not done.is_set():
                    try:
                        frame = process.stdout.readline(MAX_FRAME + 2)
                    except (OSError, ValueError):
                        return
                    while not done.is_set():
                        try:
                            mailbox.put(frame, timeout=0.1)
                            break
                        except queue.Full:
                            continue
                    if not frame or len(frame) > MAX_FRAME + 1:
                        return

            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            initial = encode(job)
            total += len(initial)
            process.stdin.write(initial)
            process.stdin.flush()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or expired.is_set():
                    raise DomainError("sandbox_timeout", 503)
                try:
                    frame = mailbox.get(timeout=remaining)
                except queue.Empty:
                    raise DomainError("sandbox_timeout", 503) from None
                if not frame:
                    if expired.is_set() or time.monotonic() >= deadline:
                        raise DomainError("sandbox_timeout", 503)
                    exit_code = process.wait(timeout=2)
                    raise DomainError(
                        "sandbox_resource_limit" if exit_code == 137 else "sandbox_worker_failed",
                        503,
                    )
                total += len(frame)
                if total > MAX_BYTES:
                    raise DomainError("sandbox_protocol_limit", 503)
                packet = decode(frame)
                if packet.get("kind") == "done":
                    process.stdin.close()
                    try:
                        code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        raise DomainError("sandbox_timeout", 503) from None
                    if code or expired.is_set() or time.monotonic() >= deadline:
                        raise DomainError("sandbox_worker_failed", 503)
                    reader.join(timeout=1)
                    if not mailbox.empty() and mailbox.get_nowait():
                        raise DomainError("sandbox_protocol_denied", 503)
                    return packet
                if set(packet) != {"kind", "seq", "op", "payload"} or packet["kind"] != "call":
                    raise DomainError("sandbox_protocol_denied", 503)
                sequence += 1
                if (
                    packet["seq"] != sequence
                    or sequence > MAX_CALLS
                    or not isinstance(packet["payload"], dict)
                ):
                    raise DomainError("sandbox_protocol_limit", 503)
                response: dict[str, Any] = {"seq": sequence}
                try:
                    response["value"] = dispatch(packet["op"], packet["payload"])
                except GatewayError as error:
                    response["error"] = {"kind": "gateway", "code": error.code, "status": 503}
                except DomainError as error:
                    response["error"] = {
                        "kind": "domain",
                        "code": error.code,
                        "status": error.status,
                    }
                if expired.is_set() or time.monotonic() >= deadline:
                    raise DomainError("sandbox_timeout", 503)
                data = encode(response)
                total += len(data)
                if total > MAX_BYTES:
                    raise DomainError("sandbox_protocol_limit", 503)
                process.stdin.write(data)
                process.stdin.flush()
        except (OSError, ValueError, RecursionError):
            raise DomainError(
                "sandbox_timeout" if expired.is_set() else "sandbox_protocol_denied", 503
            ) from None
        finally:
            done.set()
            remove_container(name)
            if process:
                if process.poll() is None:
                    process.kill()
                try:
                    process.communicate(timeout=2)
                except (ValueError, subprocess.SubprocessError):
                    pass
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                if process.stdout:
                    process.stdout.close()
            watcher.join(timeout=1)
            self.slots.release()


class SandboxedConsultationAgent(ConsultationAgent):
    def __init__(self, *args: Any, runtime: DockerRuntime, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if isinstance(self.store, PostgresAgentStore):
            options = str(conninfo_to_dict(self.settings.database_url).get("options") or "")
            scoped_settings = self.settings.model_copy(
                update={
                    "database_url": make_conninfo(
                        self.settings.database_url,
                        options=options + " -c statement_timeout=5000 -c lock_timeout=2000",
                    )
                }
            )
            # Each broker SQL operation is bounded; this does not modify database/role settings.
            self.store = PostgresAgentStore(scoped_settings, self.actor, self.store.thread_id)
            self.settings = scoped_settings
            from app.catalog import CatalogService
            from app.retrieval import PostgresEvidenceReader

            self.reader = PostgresEvidenceReader(scoped_settings)
            self.catalog = CatalogService(self.reader)
        self.runtime = runtime

    def _execute(
        self, row: dict[str, Any], message_id: str, resources: list[Any]
    ) -> dict[str, Any]:
        broker = Broker(self, row)
        resources.append(broker)
        run_id, lease = str(row["id"]), str(row["lease_token"])
        started = time.monotonic()
        job = {
            "version": 1,
            "run_id": run_id,
            "message_id": message_id,
            "thread_id": self.store.thread_id,
            "simulated": self.settings.allow_simulated_data,
            "demo_medical": self.settings.demo_medical_enabled,
            "timeout_seconds": float(self.runtime.settings.sandbox_timeout),
        }
        try:
            packet = self.runtime.execute(job, broker.dispatch)
            result, memory, exportable = broker.validate_completion(packet, message_id)
            self.store.check(run_id, lease)
            self.store.trace(
                run_id, lease, "sandbox", int((time.monotonic() - started) * 1000), "completed"
            )
            return self.fresh_result(self.store.finish(run_id, lease, result, memory, exportable))
        except DomainError as error:
            self.store.trace(
                run_id, lease, "sandbox", int((time.monotonic() - started) * 1000), error.code
            )
            raise
