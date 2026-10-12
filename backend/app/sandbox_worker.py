"""One trusted LangGraph job inside a disposable, offline and credential-free container."""

import signal
import sys
import threading
from collections.abc import Iterator, Sequence
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

from app.config import Settings
from app.consultation_agent import ConsultationAgent
from app.consultation_gateway import Draft
from app.domain import Actor, DomainError
from app.model_gateway import GatewayError
from app.retrieval import RetrievalService
from app.sandbox_wire import MAX_FRAME, SandboxJob, decode, encode


class Channel:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sequence = 0

    def call(self, operation: str, payload: dict[str, Any] | None = None) -> Any:
        with self.lock:
            self.sequence += 1
            sys.stdout.buffer.write(
                encode(
                    {
                        "kind": "call",
                        "seq": self.sequence,
                        "op": operation,
                        "payload": payload or {},
                    }
                )
            )
            sys.stdout.buffer.flush()
            response = decode(sys.stdin.buffer.readline(MAX_FRAME + 2))
            if response.get("seq") != self.sequence:
                raise DomainError("sandbox_protocol_denied", 503)
            if "error" in response:
                error = response["error"]
                if error["kind"] == "gateway":
                    raise GatewayError(error["code"])
                raise DomainError(error["code"], error["status"])
            return response["value"]


class RemoteSaver(BaseCheckpointSaver[int]):
    def __init__(self, channel: Channel) -> None:
        super().__init__()
        self.channel = channel

    def config(self, value: RunnableConfig) -> dict[str, Any]:
        return {
            "configurable": {
                key: item
                for key, item in value.get("configurable", {}).items()
                if key in ("thread_id", "checkpoint_ns", "checkpoint_id")
            }
        }

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        row = self.channel.call("checkpoint.get", {"config": self.config(config)})
        return CheckpointTuple(*row) if row else None

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        value: RunnableConfig = self.channel.call(
            "checkpoint.put",
            {"config": self.config(config), "checkpoint": checkpoint, "metadata": metadata},
        )
        return value

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        safe = [
            (key, {"code": "node_failed"} if key == "__error__" else value) for key, value in writes
        ]
        self.channel.call(
            "checkpoint.writes", {"config": self.config(config), "writes": safe, "task_id": task_id}
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        if config is None or filter or before:
            raise DomainError("checkpoint_scope_denied")
        row = self.get_tuple(config)
        if row and limit != 0:
            yield row


class RemoteStore:
    def __init__(self, channel: Channel, job: SandboxJob) -> None:
        self.channel = channel
        self.thread_id = job.thread_id
        # No dotenv read, host environment, credentials or database address enters the worker.
        self.settings = Settings(
            _env_file=None,
            database_url="unavailable",
            agent_runtime="inprocess",
            allow_simulated_data=job.simulated,
            demo_medical_education=job.demo_medical,
        )
        self.actor = Actor("scoped", "scoped", "scoped", "visitor", "unavailable")
        self.pending: dict[str, Any] | None = None

    def checkpointer(self, run_id: str, lease: str) -> BaseCheckpointSaver[int]:
        return RemoteSaver(self.channel)

    def check(self, run_id: str, lease: str) -> None:
        self.channel.call("scope.check")

    def context(self, run_id: str) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        row = self.channel.call("scope.context")
        return row[0], row[1], row[2]

    def trace(self, run_id: str, lease: str, node: str, elapsed: int, outcome: str) -> None:
        self.channel.call("trace", {"node": node, "elapsed": elapsed, "outcome": outcome})

    def finish(
        self,
        run_id: str,
        lease: str,
        result: dict[str, Any],
        memory: dict[str, Any],
        exportable: bool,
    ) -> dict[str, Any]:
        # Only the parent may commit, after successful process exit and authoritative validation.
        self.pending = {"result": result, "memory": memory, "exportable": exportable}
        return result

    def claim(self, message_id: str, question: str) -> dict[str, Any]:
        raise DomainError("sandbox_operation_denied")

    def fail(self, run_id: str, lease: str, code: str) -> None:
        raise DomainError("sandbox_operation_denied")

    def run(self, run_id: str) -> dict[str, Any]:
        raise DomainError("sandbox_operation_denied")

    def history(self, limit: int, offset: int, recent: bool = False) -> list[dict[str, Any]]:
        raise DomainError("sandbox_operation_denied")


class RemoteReader:
    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    def evidence(self, actor: Actor) -> list[dict[str, Any]]:
        value: list[dict[str, Any]] = self.channel.call("evidence.list")
        return value

    def details(self, ids: list[str]) -> list[dict[str, Any]]:
        value: list[dict[str, Any]] = self.channel.call("evidence.details", {"ids": ids})
        return value


class RemoteRetrieval(RetrievalService):
    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    def search(self, actor: Actor, question: str, limit: int = 5) -> dict[str, Any]:
        value: dict[str, Any] = self.channel.call(
            "retrieval.search", {"question": question, "limit": limit}
        )
        return value


class RemoteGateway:
    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    def answer(
        self,
        question: str,
        previous: list[str],
        evidence: list[dict[str, Any]],
        dialogue: list[dict[str, Any]] | None = None,
    ) -> Draft:
        return Draft.model_validate(
            self.channel.call(
                "model.answer",
                {
                    "question": question,
                    "ids": [str(row["id"]) for row in evidence],
                },
            )
        )


def main() -> None:
    try:
        job = SandboxJob.model_validate(decode(sys.stdin.buffer.readline(MAX_FRAME + 2)))
        # Survives launcher/API crashes: kernel-delivered timer terminates this worker itself.
        if sys.platform != "linux":
            raise ValueError("Linux sandbox worker required")
        # Windows type stubs omit POSIX signals; actual Linux behavior has a Docker exit test.
        posix_signal: Any = signal
        posix_signal.signal(posix_signal.SIGALRM, signal.SIG_DFL)
        posix_signal.setitimer(posix_signal.ITIMER_REAL, job.timeout_seconds)
        for value in (job.run_id, job.message_id, job.thread_id):
            UUID(value)
        channel = Channel()
        store = RemoteStore(channel, job)
        service = ConsultationAgent(
            store, RemoteRetrieval(channel), RemoteGateway(channel), RemoteReader(channel)
        )
        service._execute({"id": job.run_id, "lease_token": "parent-owned"}, job.message_id, [])
        if not store.pending:
            raise ValueError("missing_result")
        sys.stdout.buffer.write(encode({"kind": "done", **store.pending}))
        sys.stdout.buffer.flush()
    except Exception:
        # stdout carries only the fixed safe protocol; never provider exceptions or raw input.
        sys.stdout.buffer.write(encode({"kind": "error", "code": "sandbox_worker_failed"}))
        sys.stdout.buffer.flush()
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
