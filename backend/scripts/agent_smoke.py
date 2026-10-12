"""Real synthetic chat through the authenticated API; prints only validation metadata."""

from uuid import uuid4

import httpx

with httpx.Client(base_url="http://127.0.0.1:8001", timeout=45, trust_env=False) as client:
    session = client.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"})
    assert session.status_code == 201
    csrf = {"X-CSRF-Token": session.json()["csrf_token"]}
    thread = client.post("/api/threads", headers=csrf).json()["thread_id"]
    url = f"/api/threads/{thread}/messages"
    for question, mode in (
        ("你好", "fixed"),
        ("第一次了解医美，不做项目也能咨询吗？", "generated"),
        ("那到店咨询需要提前准备什么？", "generated"),
        ("我怀孕了，可以做水光吗？", "handoff"),
    ):
        payload = {"message_id": str(uuid4()), "question": question}
        response = client.post(url, headers=csrf, json=payload)
        assert response.status_code == 200, response.json().get("code")
        result = response.json()
        print(
            {
                "mode": result["mode"],
                "stage": result["funnel_stage"],
                "citations": len(result["evidence_ids"]),
                "handoff_reason": result["handoff_reason"],
            }
        )
        assert result["mode"] == mode
        assert client.post(url, headers=csrf, json=payload).json() == result
        run = client.get(f"/api/threads/{thread}/runs/{result['run_id']}")
        assert run.status_code == 200 and run.json()["status"] == "completed"
    assert len(client.get(url).json()["items"]) == 8
    assert client.post("/api/visitor-sessions/logout", headers=csrf).status_code == 200
    assert client.get(url).status_code == 401
print("Real LangGraph/Qwen agent smoke passed; synthetic input only")
