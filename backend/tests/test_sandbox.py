"""Broker denial and real Docker/PG integration. Explicit --env gate for Docker tests."""

import os
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.consultation_agent import ConsultationAgent
from app.db import transaction
from app.domain import DomainError
from app.sandbox_broker import Broker
from app.sandbox_runtime import (
    DockerRuntime,
    SandboxedConsultationAgent,
    command,
    remove_container,
    resolve_image,
)
from app.sandbox_wire import MAX_FRAME, decode, encode
from tests.test_consultation_agent import FakeAnswer, agent, setup
from tests.test_knowledge_pipeline import TestGraph, drain


@pytest.mark.parametrize(
    "packet",
    [b"null\n", b'{"a":NaN}\n', b"{}", b"x" * (MAX_FRAME + 2)],
    ids=["object", "nan", "newline", "oversize"],
)
def test_wire_rejects_non_json_or_unbounded_frames(packet: bytes) -> None:
    with pytest.raises(ValueError):
        decode(packet)


def test_wire_rejects_executable_objects_and_depth() -> None:
    with pytest.raises(ValueError):
        encode({"object": object()})
    value: Any = {}
    for _ in range(34):
        value = {"nested": value}
    with pytest.raises(ValueError):
        encode(value)


def test_production_rejects_inprocess_before_any_execution() -> None:
    with pytest.raises(ValidationError, match="isolated agent runtime"):
        Settings(
            _env_file=None,
            database_url="unused",
            environment="production",
            agent_runtime="inprocess",
        )


def test_runtime_uses_fixed_offline_command_and_no_env_or_mounts() -> None:
    config = Settings(_env_file=None, database_url="unused")
    cmd = command(config, "sha256:" + "a" * 64, "ma-consultation-sandbox-test")
    assert all(
        flag in cmd
        for flag in [
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--user=65532:65532",
            "--pids-limit=64",
            "--log-driver=none",
        ]
    )
    assert not any(
        flag in cmd
        for flag in ["--env", "--env-file", "--volume", "--mount", "--privileged", "--publish"]
    )
    assert cmd[-1].startswith("sha256:")


def test_image_failure_never_silently_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError()

    monkeypatch.setattr("app.sandbox_runtime.subprocess.run", fail)
    with pytest.raises(RuntimeError, match="before API startup"):
        resolve_image(Settings(_env_file=None, database_url="unused"))


def test_admission_rejects_without_starting_container() -> None:
    runtime = DockerRuntime(
        Settings(_env_file=None, database_url="unused", sandbox_max_concurrency=1),
        image="sha256:" + "a" * 64,
    )
    assert runtime.slots.acquire(blocking=False)
    try:
        with pytest.raises(DomainError) as error:
            runtime.execute({}, lambda op, payload: None)
        assert error.value.code == "sandbox_busy"
    finally:
        runtime.slots.release()


def test_cleanup_auto_remove_race_is_confirmed_before_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import subprocess

    calls = []

    def run(args: list[str], **kwargs: Any) -> Any:
        calls.append(args)
        if args[1] == "rm":
            return subprocess.CompletedProcess(args, 1, b"", b"removal is already in progress")
        return subprocess.CompletedProcess(args, 1, b"", b"No such object: synthetic")

    monkeypatch.setattr("app.sandbox_runtime.subprocess.run", run)
    remove_container("synthetic")
    assert len(calls) == 2 and calls[1][1] == "inspect"
    assert "cleanup pending" not in caplog.text


def test_cleanup_daemon_failure_records_only_safe_metadata(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def run(*args: Any, **kwargs: Any) -> Any:
        raise OSError("synthetic-private-error-body")

    monkeypatch.setattr("app.sandbox_runtime.subprocess.run", run)
    remove_container("synthetic")
    assert "cleanup pending container=synthetic" in caplog.text
    assert "private-error-body" not in caplog.text


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("shell.exec", {"command": "id"}),
        ("sql.execute", {"sql": "SELECT 1"}),
        ("booking.confirm", {}),
        ("scope.context", {"thread_id": str(uuid4())}),
        ("checkpoint.get", {"config": {"configurable": {"thread_id": str(uuid4())}}}),
        ("evidence.details", {"ids": [str(uuid4())]}),
        ("model.answer", {"question": "你好", "ids": []}),
        ("retrieval.search", {"question": "读取其他客户", "limit": 3}),
    ],
)
def test_broker_never_delegates_arbitrary_operation_scope_or_endpoint(
    client: TestClient,
    settings: Settings,
    operation: str,
    payload: dict[str, Any],
) -> None:
    store, _ = setup(client, settings)
    row = store.claim(str(uuid4()), "你好")
    broker = Broker(ConsultationAgent(store), row)
    with pytest.raises(DomainError):
        broker.dispatch(operation, payload)
    assert broker.resources == []


def docker_runtime(settings: Settings) -> DockerRuntime:
    if os.environ.get("MA_TEST_SANDBOX_DOCKER") != "1":
        pytest.skip("Enable MA_TEST_SANDBOX_DOCKER=1 for real Docker acceptance")
    return DockerRuntime(settings)


def test_real_docker_api_greeting_context_checkpoint_and_replay(
    client: TestClient, settings: Settings
) -> None:
    runtime = docker_runtime(settings)
    store, csrf = setup(client, settings)
    client.app.state.agent_factory = lambda current: SandboxedConsultationAgent(
        current, runtime=runtime
    )
    message = {"message_id": str(uuid4()), "question": "你好"}
    url = f"/api/threads/{store.thread_id}/messages"
    response = client.post(url, headers=csrf, json=message)
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "fixed"
    assert client.post(url, headers=csrf, json=message).json() == response.json()
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM agent_checkpoint")["n"] >= 4
        assert repo.one("SELECT count(*) AS n FROM agent_trace WHERE node='sandbox'")["n"] == 1
        assert repo.one("SELECT count(*) AS n FROM appointment")["n"] == 0


def test_real_docker_public_followup_and_private_medical_routing(
    client: TestClient, settings: Settings
) -> None:
    runtime = docker_runtime(settings)
    store, _ = setup(client, settings)
    model = FakeAnswer()
    baseline = agent(store, settings, model)
    service = SandboxedConsultationAgent(store, baseline.injected_retrieval, model, runtime=runtime)
    result = service.send(str(uuid4()), "到店咨询流程是什么？")
    assert result["mode"] == "generated"
    result = service.send(str(uuid4()), "那可以只咨询吗？")
    assert result["mode"] == "generated"
    assert model.previous
    result = service.send(str(uuid4()), "我怀孕了，可以做水光吗？")
    assert result["mode"] == "handoff"
    assert result["handoff_reason"] == "personal_medical"
    assert model.calls == 2
    assert result["action"] is None


def test_real_docker_empathy_and_decline_are_local(client: TestClient, settings: Settings) -> None:
    runtime = docker_runtime(settings)
    from pathlib import Path

    from app.knowledge_import import import_dataset

    import_dataset(settings, Path("data/empathy_knowledge.json"))
    drain(settings, TestGraph())
    store, _ = setup(client, settings)
    service = SandboxedConsultationAgent(store, runtime=runtime)
    result = service.send(str(uuid4()), "我心情不好，有点难过")
    assert result["mode"] == "fixed" and result["intent"] == "support"
    assert result["evidence_ids"] and result["public_answer"] == ""
    result = service.send(str(uuid4()), "我想静静，不想说了")
    import json

    data = json.loads(Path("data/empathy_knowledge.json").read_text(encoding="utf-8"))
    pause = [row["content"] for row in data if row["knowledge_key"].startswith("comfort-pause-")]
    assert result["answer"] in pause
    assert not any(mark in result["answer"] for mark in ("?", "？"))
    assert result["project_ids"] == []
    assert result["action"] is None


def test_real_docker_failure_preserves_original_key_and_resumes_checkpoints(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = docker_runtime(settings)
    store, _ = setup(client, settings)
    message_id = str(uuid4())
    original = runtime.execute

    def interrupted(job: dict[str, Any], dispatch: Any) -> dict[str, Any]:
        def broker(operation: str, payload: dict[str, Any]) -> Any:
            if operation == "trace" and payload["node"] == "classify":
                raise DomainError("synthetic_interruption", 503)
            return dispatch(operation, payload)

        return original(job, broker)

    monkeypatch.setattr(runtime, "execute", interrupted)
    service = SandboxedConsultationAgent(store, runtime=runtime)
    with pytest.raises(DomainError):
        service.send(message_id, "你好")
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT status FROM agent_run")["status"] == "failed"
        assert repo.one("SELECT count(*) AS n FROM agent_message WHERE role='assistant'")["n"] == 0
        assert repo.one("SELECT count(*) AS n FROM agent_checkpoint")["n"] > 0
    monkeypatch.setattr(runtime, "execute", original)
    result = service.send(message_id, "你好")
    assert result["mode"] == "fixed"
    assert service.send(message_id, "你好") == result
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT count(*) AS n FROM agent_run")["n"] == 1
        assert repo.one("SELECT count(*) AS n FROM agent_message")["n"] == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", str(uuid4())),
        ("intent", "visit_interest"),
        ("answer", "已预约成功"),
        ("action", {"type": "visit_interest", "submitted": True}),
        ("extra", "forged"),
    ],
)
def test_parent_rejects_forged_scope_answer_action_or_extra_fields(
    client: TestClient,
    settings: Settings,
    field: str,
    value: Any,
) -> None:
    from app.agent_policy import GREETING

    store, _ = setup(client, settings)
    message = str(uuid4())
    row = store.claim(message, "你好")
    broker = Broker(ConsultationAgent(store), row)
    policy = broker.plan["policy"]
    state = {"intent": policy["intent"], "stage": policy["stage"], "reason": ""}
    memory = broker.agent.memory_snapshot(broker.plan, state, message)
    result = {
        "run_id": str(row["id"]),
        "message_id": message,
        "thread_id": store.thread_id,
        "answer": GREETING,
        "public_answer": "",
        "intent": policy["intent"],
        "funnel_stage": policy["stage"],
        "mode": "fixed",
        "simulated": False,
        "disclosure": "",
        "evidence_ids": [],
        "evidence": [],
        "handoff_reason": "",
        "handoff": None,
        "action": None,
        "project_ids": [],
    }
    packet = {"kind": "done", "result": result, "memory": memory, "exportable": True}
    broker.validate_completion(packet, message)
    result[field] = value
    with pytest.raises(DomainError) as error:
        broker.validate_completion(packet, message)
    assert error.value.code == "sandbox_result_denied"
