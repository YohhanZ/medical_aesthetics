"""Real customer proxy/agent smoke; fixed synthetic input, metadata output only."""

from uuid import uuid4

import httpx

with httpx.Client(base_url="http://127.0.0.1:5173", timeout=45, trust_env=False) as client:
    stores = client.get("/api/public/stores")
    assert stores.status_code == 200 and stores.json()["items"]
    created = client.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"})
    assert created.status_code == 201
    session = client.get("/api/visitor-sessions/current").json()
    assert client.get("/api/visitor-sessions/current").json() == session
    csrf = {"X-CSRF-Token": session["csrf_token"]}
    thread = client.post("/api/threads", headers=csrf).json()["thread_id"]
    projects = client.get("/api/catalog/projects").json()["items"]
    assert len(projects) == 30 and all(project["simulated"] for project in projects)
    payload = {"message_id": str(uuid4()), "question": "想了解补水护理"}
    url = f"/api/threads/{thread}/messages"
    response = client.post(url, headers=csrf, json=payload)
    assert response.status_code == 200, response.json().get("code")
    result = response.json()
    assert result["mode"] == "generated"
    card = next(project for project in result["projects"] if project["key"] == "hydration")
    assert card["detail_url"] == f"/#project/{card['id']}"
    assert client.get(card["image_url"]).status_code == 200
    assert client.get(f"/api/catalog/projects/{card['id']}").json() == card
    assert client.post(url, headers=csrf, json=payload).json() == result
    assert len(client.get(url + "?recent=true").json()["items"]) == 2
    assert client.get("/api/threads").json()["items"][0]["thread_id"] == thread
    switched = client.post(
        "/api/visitor-sessions", headers=csrf, json={"store_code": "demo-hangzhou"}
    )
    assert switched.status_code == 201
    assert client.get("/api/catalog/projects").json() == {"items": []}
    assert client.get(f"/api/catalog/projects/{card['id']}").status_code == 404
    assert client.get(url).status_code == 404
    assert (
        client.post(
            "/api/visitor-sessions/logout", headers={"X-CSRF-Token": switched.json()["csrf_token"]}
        ).status_code
        == 200
    )
    assert client.get("/api/visitor-sessions/current").status_code == 401
    print(
        {
            "proxy": "passed",
            "model_mode": result["mode"],
            "catalog_projects": len(projects),
            "related_cards": len(result["projects"]),
            "session_reload": "passed",
            "cross_store": "denied",
            "replay": "passed",
            "input": "synthetic-only",
        }
    )
