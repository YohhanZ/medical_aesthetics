"""Exercise the dev admin proxy with local synthetic credentials; never print credentials."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx

from app.config import Settings
from app.domain import now
from app.seed import OTHER_STORE, STORE

settings = Settings()
if settings.environment != "development" or not settings.allow_simulated_data:
    raise SystemExit("Admin smoke is only allowed on local simulated development data")
password = (Path(__file__).parents[2] / "runtime" / "m1-seed-password.txt").read_text().strip()
headers = {"Origin": "http://127.0.0.1:5175"}
with httpx.Client(base_url="http://127.0.0.1:5175/api", trust_env=False, timeout=10) as client:
    tokens = []
    try:
        for username in ("demo-author", "demo-reviewer"):
            response = client.post(
                "/staff-sessions",
                headers=headers,
                json={"username": username, "password": password},
            )
            assert response.status_code == 200
            tokens.append(response.json()["access_token"])
        author = {**headers, "Authorization": f"Bearer {tokens[0]}"}
        reviewer = {**headers, "Authorization": f"Bearer {tokens[1]}"}
        profile = client.get("/staff/me", headers=author)
        assert profile.status_code == 200
        assert [store["id"] for store in profile.json()["stores"]] == [STORE]
        assert client.get(f"/stores/{OTHER_STORE}/knowledge", headers=author).status_code == 403
        base = f"/stores/{STORE}/knowledge"
        result = client.post(
            base,
            headers=author,
            json={
                "knowledge_key": f"admin-http-smoke-{uuid4().hex[:12]}",
                "category": "operational",
                "title": "后台代理合成验收资料",
                "content": "仅用于本地 HTTP 验收，结束后撤回。",
                "source": "本项目合成验收",
                "simulated": True,
                "valid_until": (now() + timedelta(days=1)).isoformat(),
            },
        )
        assert result.status_code == 201
        version = result.json()["version_id"]
        review_body = {"approved": True, "reason": "独立开发账号仅复核合成运营资料"}
        assert (
            client.post(f"{base}/{version}/review", headers=author, json=review_body).status_code
            == 403
        )
        assert (
            client.post(f"{base}/{version}/review", headers=reviewer, json=review_body).status_code
            == 200
        )
        assert client.post(f"{base}/{version}/publish", headers=reviewer).json() == {
            "status": "publishing"
        }
        listing = client.get(base, headers=author).json()
        assert any(
            row["id"] == version and row["status"] == "publishing" for row in listing["items"]
        )
        assert client.post(f"{base}/{version}/withdraw", headers=reviewer).status_code == 200
    finally:
        for credential in tokens:
            client.post(
                "/staff-sessions/logout",
                headers={**headers, "Authorization": f"Bearer {credential}"},
            )
print(
    "Admin HTTP smoke passed: proxy/login/grants/create/independent review/publish/withdraw/logout"
)
