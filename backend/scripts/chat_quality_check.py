"""Capture real, synthetic-only consultation replies for human fluency/context review."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "backend" / "data" / "chat_quality_cases.json"
OUTPUT = ROOT / "runtime" / "chat-quality-report.json"


def evaluate(only: list[str], demo: bool = False, empathy: bool = False) -> None:
    case_file = (
        CASES.with_name("empathy_chat_cases.json")
        if empathy
        else CASES.with_name("demo_chat_cases.json")
        if demo
        else CASES
    )
    report_file = (
        OUTPUT.with_name("empathy-chat-report.json")
        if empathy
        else OUTPUT.with_name("demo-chat-report.json")
        if demo
        else OUTPUT
    )
    cases = json.loads(case_file.read_text(encoding="utf-8"))
    if only:
        cases = [case for case in cases if case["id"] in only]
    assert cases and all(case["simulated"] for case in cases)
    output = (
        report_file.with_name(
            ("empathy-chat-" if empathy else "demo-chat-" if demo else "chat-quality-")
            + "-".join(case["id"] for case in cases)
            + ".json"
        )
        if only
        else report_file
    )
    report: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "scope": "Real local customer proxy, synthetic-only; human review, no medical approval",
        "cases": [],
    }
    output.parent.mkdir(exist_ok=True)
    for case in cases:
        captured: dict[str, Any] = {"id": case["id"], "title": case["title"], "turns": []}
        with httpx.Client(base_url="http://127.0.0.1:5173", timeout=50, trust_env=False) as client:
            session = client.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"})
            session.raise_for_status()
            csrf = {"X-CSRF-Token": session.json()["csrf_token"]}
            thread = client.post("/api/threads", headers=csrf)
            thread.raise_for_status()
            captured["thread_id"] = thread.json()["thread_id"]
            url = f"/api/threads/{captured['thread_id']}/messages"
            try:
                for question in case["turns"]:
                    started = time.monotonic()
                    payload = {"message_id": str(uuid4()), "question": question}
                    try:
                        response = client.post(url, headers=csrf, json=payload)
                        result = response.json()
                        turn = {
                            "question": question,
                            "status": response.status_code,
                            "elapsed_seconds": round(time.monotonic() - started, 2),
                            "result": result
                            if response.status_code == 200
                            else {
                                "code": result.get("code"),
                                "request_id": result.get("request_id"),
                            },
                        }
                        if response.status_code == 200:
                            replay = client.post(url, headers=csrf, json=payload)
                            turn["replay_consistent"] = (
                                replay.status_code == 200 and replay.json() == result
                            )
                            run = client.get(
                                f"/api/threads/{captured['thread_id']}/runs/{result['run_id']}"
                            )
                            turn["trace"] = (
                                run.json().get("trace", []) if run.status_code == 200 else []
                            )
                    except (httpx.HTTPError, ValueError) as error:
                        turn = {
                            "question": question,
                            "status": 0,
                            "error_type": type(error).__name__,
                            "elapsed_seconds": round(time.monotonic() - started, 2),
                        }
                    captured["turns"].append(turn)
                    print(
                        json.dumps(
                            {
                                "case": case["id"],
                                "turn": len(captured["turns"]),
                                "status": turn["status"],
                                "mode": turn.get("result", {}).get("mode"),
                                "seconds": turn["elapsed_seconds"],
                            }
                        ),
                        flush=True,
                    )
                    report["cases"] = [c for c in report["cases"] if c["id"] != captured["id"]]
                    report["cases"].append(captured)
                    output.write_text(
                        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )
                history = client.get(url, params={"limit": 100, "offset": 0})
                captured["history_count"] = len(history.json().get("items", []))
                captured["history_status"] = history.status_code
            finally:
                captured["logout_status"] = client.post(
                    "/api/visitor-sessions/logout", headers=csrf
                ).status_code
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "cases": len(report["cases"]),
                "turns": sum(len(c["turns"]) for c in report["cases"]),
                "report": str(output),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", default=[])
    dataset = parser.add_mutually_exclusive_group()
    dataset.add_argument("--demo", action="store_true")
    dataset.add_argument("--empathy", action="store_true")
    args = parser.parse_args()
    evaluate(args.case, args.demo, args.empathy)
