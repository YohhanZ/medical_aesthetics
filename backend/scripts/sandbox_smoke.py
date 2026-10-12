"""Actual localhost API/Qwen chain; synthetic questions and separate anonymous credentials."""

import json
from pathlib import Path
from uuid import uuid4

import httpx


def main() -> None:
    report = []
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=65, trust_env=False) as client:
        assert client.get("/health/ready").json()["agent_runtime"] == "docker"
        session = client.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"})
        assert session.status_code == 201
        csrf = {"X-CSRF-Token": session.json()["csrf_token"]}
        thread = client.post("/api/threads", headers=csrf).json()["thread_id"]
        url = f"/api/threads/{thread}/messages"
        try:
            for question in (
                "你好",
                "我担心预算，补水护理多少钱？",
                "那护理步骤包括什么？",
                "我想静静，不想说了",
            ):
                payload = {"message_id": str(uuid4()), "question": question}
                response = client.post(url, headers=csrf, json=payload)
                assert response.status_code == 200, response.json().get("code")
                result = response.json()
                replay = client.post(url, headers=csrf, json=payload)
                assert replay.status_code == 200 and replay.json() == result
                run = client.get(f"/api/threads/{thread}/runs/{result['run_id']}").json()
                sandbox = [row for row in run["trace"] if row["node"] == "sandbox"]
                assert len(sandbox) == 1 and sandbox[0]["outcome"] == "completed"
                assert result["action"] is None
                report.append(
                    {"question": question, "result": result, "sandbox": sandbox[0], "replay": True}
                )
                print(
                    json.dumps({"mode": result["mode"], "sandbox": sandbox[0]}, ensure_ascii=False),
                    flush=True,
                )
            assert report[1]["result"]["mode"] == "generated"
            assert "298" in report[1]["result"]["answer"]
            assert report[2]["result"]["mode"] == "generated"
            assert (
                report[3]["result"]["intent"] == "support"
                and report[3]["result"]["mode"] == "fixed"
            )
            assert len(client.get(url).json()["items"]) == 8
        finally:
            assert client.post("/api/visitor-sessions/logout", headers=csrf).status_code == 200
        assert client.get(url).status_code == 401
    path = Path(__file__).resolve().parents[2] / "runtime" / "sandbox-chat-report.json"
    path.write_text(
        json.dumps({"runtime": "docker", "turns": report}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("Actual sandbox/API/Qwen smoke: 4 rounds, replay/history/logout passed")


if __name__ == "__main__":
    main()
