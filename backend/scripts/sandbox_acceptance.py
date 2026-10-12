"""Real Docker boundary/fault acceptance with a separate, synthetic-only probe image."""

import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.domain import DomainError
from app.sandbox_runtime import DockerRuntime, command, remove_container, resolve_image
from app.sandbox_wire import MAX_FRAME, encode


def denied(operation: str, payload: dict[str, object]) -> object:
    raise DomainError("sandbox_operation_denied")


def main() -> None:
    settings = Settings(_env_file=None, database_url="unused", sandbox_timeout=10)
    image = subprocess.run(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            "medical-consultation-sandbox-probe:local",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    runtime = DockerRuntime(settings, image=image)
    report: dict[str, object] = {"worker_image": resolve_image(settings), "probe_image": image}
    report["boundaries"] = runtime.execute({"probe": "boundaries"}, denied)["checks"]
    faults = []
    for mode, expected in [
        ("malformed", "sandbox_protocol_denied"),
        ("oversize", "sandbox_protocol_denied"),
        ("oom", "sandbox_resource_limit"),
        ("hang", "sandbox_timeout"),
    ]:
        started = time.monotonic()
        try:
            runtime.execute({"probe": mode}, denied)
            code = "unexpected_success"
        except DomainError as error:
            code = error.code
        faults.append(
            {
                "case": mode,
                "code": code,
                "passed": code == expected,
                "elapsed_seconds": round(time.monotonic() - started, 2),
            }
        )
    operation = runtime.execute({"probe": "operation"}, denied)
    report["operation_denied"] = operation["denied"] == "sandbox_operation_denied"
    report["faults"] = faults
    # Leave stdin open but provide no broker response. Worker must exit using its own timer.
    name = "ma-consultation-sandbox-" + uuid4().hex
    started = time.monotonic()
    process = subprocess.Popen(
        command(settings, str(report["worker_image"]), name),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert process.stdin and process.stdout
        process.stdin.write(
            encode(
                {
                    "version": 1,
                    "run_id": str(uuid4()),
                    "message_id": str(uuid4()),
                    "thread_id": str(uuid4()),
                    "simulated": True,
                    "demo_medical": False,
                    "timeout_seconds": 10.0,
                }
            )
        )
        process.stdin.flush()
        first = process.stdout.readline(MAX_FRAME + 2)
        exit_code = process.wait(timeout=16)
        report["worker_self_timeout"] = {
            "exit_code": exit_code,
            "passed": exit_code == 142 and bool(first),
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }
    finally:
        remove_container(name)
        if process.poll() is None:
            process.kill()
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()
    remaining = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            "label=medical.consultation.sandbox=1",
            "--format",
            "{{.Names}}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.splitlines()
    report["remaining_containers"] = remaining
    report["passed"] = (
        all(report["boundaries"].values())
        and all(row["passed"] for row in faults)
        and report["operation_denied"]
        and report["worker_self_timeout"]["passed"]  # type: ignore[index]
        and not remaining
    )  # type: ignore[union-attr]
    path = Path(__file__).resolve().parents[2] / "runtime" / "sandbox-boundary-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
