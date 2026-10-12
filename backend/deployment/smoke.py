"""Cloud HTTPS demo acceptance, synthetic input only; never prints passwords/tokens/content."""

import argparse
import json
import re
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from dotenv import dotenv_values

STORE = "00000000-0000-4000-8000-000000000011"
OTHER_STORE = "00000000-0000-4000-8000-000000000012"


def checked(response: httpx.Response) -> Any:
    if response.status_code >= 400:
        try:
            code = response.json().get("code", "unknown")
        except ValueError:
            code = "non_json_error"
        raise RuntimeError(f"HTTP {response.status_code}, safe code={code}")
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://43.142.39.108:8080")
    parser.add_argument("--credential-file", type=Path, required=True)
    args = parser.parse_args()
    if not args.base_url.startswith("https://"):
        raise RuntimeError("Cloud acceptance requires verified HTTPS")
    password = dotenv_values(args.credential_file)["M1_SEED_PASSWORD"]
    assert password
    metadata: dict[str, Any] = {}
    with httpx.Client(base_url=args.base_url, timeout=65, trust_env=False) as customer:
        for path in ("/", "/admin/"):
            html = customer.get(path)
            assert html.status_code == 200 and "text/html" in html.headers["content-type"]
            assert 'type="module"' in html.text
            for asset in re.findall(r'(?:src|href)="([^"]+)"', html.text):
                if asset.startswith("/"):
                    assert customer.get(asset).status_code == 200
        assert "/admin/assets/" in customer.get("/admin/").text
        stores = checked(customer.get("/api/public/stores"))
        assert stores["items"] and all(item["simulated"] for item in stores["items"])
        session = checked(
            customer.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"})
        )
        csrf = {"X-CSRF-Token": session["csrf_token"]}
        assert all(cookie.secure for cookie in customer.cookies.jar)
        thread = checked(customer.post("/api/threads", headers=csrf, json={}))["thread_id"]
        base = f"/api/threads/{thread}"
        projects = checked(customer.get("/api/catalog/projects"))["items"]
        assert projects and all(project["simulated"] for project in projects)
        chat: list[dict[str, Any]] = []
        turns = [
            ("你好", "fixed"),
            ("我预算只有300元，想了解补水护理", "generated"),
            ("它一般需要多久？", "generated"),
            ("我今天心情不好，只想静静，不想说了", "fixed"),
            ("我想预约到店咨询", "handoff"),
        ]
        for question, mode in turns:
            payload = {"message_id": str(uuid4()), "question": question}
            result = checked(customer.post(base + "/messages", headers=csrf, json=payload))
            print(
                json.dumps(
                    {
                        "phase": "chat",
                        "turn": len(chat) + 1,
                        "mode": result["mode"],
                        "reason": result.get("reason"),
                    }
                ),
                flush=True,
            )
            assert result["mode"] == mode
            assert result["answer"]
            if question == "我想预约到店咨询":
                assert result["action"] == {"type": "visit_interest", "submitted": False}
                assert not result["handoff"]["connected"]
            run = checked(customer.get(base + f"/runs/{result['run_id']}"))
            assert any(
                trace["node"] == "sandbox" and trace["outcome"] == "completed"
                for trace in run["trace"]
            )
            if question.startswith("我预算"):
                assert "298" in result["answer"]
                assert any(project["key"] == "hydration" for project in result["projects"])
            if question == "它一般需要多久？":
                assert "补水" in result["answer"]
            assert checked(customer.post(base + "/messages", headers=csrf, json=payload)) == result
            for card in result["projects"]:
                assert customer.get(card["image_url"]).status_code == 200
                assert customer.get(f"/api/catalog/projects/{card['id']}").status_code == 200
            chat.append(
                {"mode": result["mode"], "run_id": result["run_id"], "sandbox": "completed"}
            )
        assert len(checked(customer.get(base + "/messages?recent=true"))["items"]) == 10
        state = checked(customer.get(base + "/booking"))
        assert state["simulated_verification"] is True
        draft_body = {
            "request_key": str(uuid4()),
            "trigger_run_id": chat[-1]["run_id"],
            "name": "合成云端验收",
            "phone": "19900000009",
            "desired_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            "intention": "不确定项目，先咨询",
        }
        draft = checked(customer.post(base + "/appointment-drafts", headers=csrf, json=draft_body))
        draft_path = base + f"/appointment-drafts/{draft['id']}"
        receipt = checked(
            customer.post(
                draft_path + "/verification",
                headers=csrf,
                json={"request_key": str(uuid4()), "sms_consent": True},
            )
        )
        assert receipt["simulated"] and receipt["simulated_code"]
        verified = checked(
            customer.post(
                base + f"/contact-verifications/{receipt['id']}/verify",
                headers=csrf,
                json={"code": receipt["simulated_code"]},
            )
        )
        assert verified["verified"]
        confirmation = {
            "request_key": str(uuid4()),
            "snapshot_hash": draft["snapshot_hash"],
            "verification_id": receipt["id"],
            "accepted": True,
            "confirmation_text": "确认提交预约申请，等待门店确认",
        }
        appointment = checked(
            customer.post(draft_path + "/confirm", headers=csrf, json=confirmation)
        )
        assert appointment["simulated"] and appointment["state"] == "pending_store_confirmation"
        assert (
            checked(customer.post(draft_path + "/confirm", headers=csrf, json=confirmation))
            == appointment
        )
        with httpx.Client(base_url=args.base_url, timeout=20, trust_env=False) as staff:

            def login(username: str) -> dict[str, str]:
                token = checked(
                    staff.post(
                        "/api/staff-sessions", json={"username": username, "password": password}
                    )
                )["access_token"]
                return {"Authorization": "Bearer " + token}

            author = login("demo-author")
            assert staff.get(f"/api/stores/{STORE}/appointments", headers=author).status_code == 403
            operator = login("demo-operator")
            checked(staff.get("/api/staff/me", headers=operator))
            assert (
                staff.get(f"/api/stores/{OTHER_STORE}/appointments", headers=operator).status_code
                == 403
            )
            detail = checked(
                staff.get(f"/api/stores/{STORE}/appointments/{appointment['id']}", headers=operator)
            )
            confirmed = checked(
                staff.post(
                    f"/api/stores/{STORE}/appointments/{appointment['id']}/decision",
                    headers=operator,
                    json={
                        "request_key": str(uuid4()),
                        "expected_version": detail["version"],
                        "action": "confirm",
                        "accepted": True,
                        "availability_checked": True,
                    },
                )
            )
            assert confirmed["state"] == "confirmed"
            assert (
                checked(customer.get(base + "/booking"))["appointments"][0]["state"] == "confirmed"
            )
            consultant = login("demo-consultant")
            checked(staff.get("/api/staff/me", headers=consultant))
            checked(staff.post("/api/staff-sessions/logout", headers=consultant))
        with httpx.Client(base_url=args.base_url, timeout=20, trust_env=False) as other:
            checked(other.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"}))
            assert other.get(base + "/messages").status_code == 404
        medical = checked(
            customer.post(
                base + "/messages",
                headers=csrf,
                json={"message_id": str(uuid4()), "question": "我怀孕了，可以做水光吗？"},
            )
        )
        assert medical["mode"] == "handoff" and not medical["handoff"]["connected"]
        checked(customer.post("/api/visitor-sessions/logout", headers=csrf))
        assert customer.get(base + "/messages").status_code == 401
        metadata.update(
            {
                "https": "verified",
                "frontend_assets": "passed",
                "secure_cookies": "passed",
                "catalog_projects": len(projects),
                "chat": chat,
                "context": "passed",
                "empathy_pause": "passed",
                "replay_history": "passed",
                "booking": "simulated-confirmed",
                "staff_roles": "passed",
                "cross_visitor_and_store": "denied",
                "personal_medical": "handoff",
                "logout": "denied",
                "input": "synthetic-only",
            }
        )
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Assertion/transport errors may retain local credentials in object repr/traceback.
        frames = traceback.extract_tb(error.__traceback__)
        location = f"{Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else "unknown"
        safe = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print(f"Failure location: {location}")
        raise SystemExit(f"Cloud smoke failed: {safe}; sensitive details suppressed") from None
