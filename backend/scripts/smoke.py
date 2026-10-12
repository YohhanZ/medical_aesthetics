"""HTTP smoke on isolated development API; synthetic input only, empty/published states."""

import httpx

with httpx.Client(base_url="http://127.0.0.1:8001", timeout=10, trust_env=False) as client:
    ready = client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["milestone"] == "M2-knowledge"
    session = client.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"})
    assert session.status_code == 201 and session.json()["simulated"]
    csrf = {"X-CSRF-Token": session.json()["csrf_token"]}
    created = client.post("/api/threads", headers=csrf)
    assert created.status_code == 201
    thread = client.get(f"/api/threads/{created.json()['thread_id']}")
    assert thread.status_code == 200
    evidence = client.get("/api/knowledge/evidence")
    assert evidence.status_code == 200
    allowed = {item["id"] for item in evidence.json()["items"]}
    search = client.post(
        "/api/knowledge/search",
        headers=csrf,
        json={"question": "第一次了解医美，不做项目也能咨询吗？"},
    )
    assert search.status_code == 200
    assert all(item["id"] in allowed for item in search.json()["items"])
    if allowed:
        assert search.json()["method"] in ("lexical", "hybrid") and search.json()["items"]
    else:
        assert search.json()["method"] == "none"
    assert client.post("/api/visitor-sessions/logout", headers=csrf).status_code == 200
    assert client.get(f"/api/threads/{created.json()['thread_id']}").status_code == 401
print("HTTP smoke passed: readiness/session/thread/evidence/search/logout; synthetic input only")
