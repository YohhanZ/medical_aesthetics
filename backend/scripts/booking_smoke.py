"""Local simulated booking through the customer proxy; refuses a real SMS provider."""

from datetime import timedelta
from uuid import uuid4

import httpx

from app.booking_models import CONFIRMATION_TEXT
from app.domain import now


def main() -> None:
    with httpx.Client(base_url="http://127.0.0.1:5173", trust_env=False, timeout=20) as client:
        session = client.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"})
        session.raise_for_status()
        headers = {"X-CSRF-Token": session.json()["csrf_token"]}
        thread_response = client.post("/api/threads", headers=headers, json={})
        thread_response.raise_for_status()
        base = f"/api/threads/{thread_response.json()['thread_id']}"
        answer = client.post(
            base + "/messages",
            headers=headers,
            json={"message_id": str(uuid4()), "question": "我想预约到店咨询"},
        )
        answer.raise_for_status()
        state = client.get(base + "/booking")
        state.raise_for_status()
        assert state.json().get("simulated_verification") is True, (
            "Smoke requires explicit local simulated verification; no real SMS is sent"
        )
        data = {
            "request_key": str(uuid4()),
            "trigger_run_id": answer.json()["run_id"],
            "name": "合成验收",
            "phone": "19900000009",
            "desired_at": (now() + timedelta(days=2)).isoformat(),
            "intention": "不确定项目，先咨询",
        }
        response = client.post(base + "/appointment-drafts", headers=headers, json=data)
        response.raise_for_status()
        draft = response.json()
        assert client.post(base + "/appointment-drafts", headers=headers, json=data).json() == draft
        path = base + f"/appointment-drafts/{draft['id']}"
        response = client.post(
            path + "/verification",
            headers=headers,
            json={"request_key": str(uuid4()), "sms_consent": True},
        )
        response.raise_for_status()
        receipt = response.json()
        assert receipt["simulated"] and receipt["simulated_code"]
        response = client.post(
            base + f"/contact-verifications/{receipt['id']}/verify",
            headers=headers,
            json={"code": receipt["simulated_code"]},
        )
        response.raise_for_status()
        assert response.json()["verified"]
        confirm = {
            "request_key": str(uuid4()),
            "snapshot_hash": draft["snapshot_hash"],
            "verification_id": receipt["id"],
            "accepted": True,
            "confirmation_text": CONFIRMATION_TEXT,
        }
        response = client.post(path + "/confirm", headers=headers, json=confirm)
        response.raise_for_status()
        appointment = response.json()
        assert appointment["state"] == "pending_store_confirmation" and appointment["simulated"]
        assert client.post(path + "/confirm", headers=headers, json=confirm).json() == appointment
        assert client.get(base + "/booking").json()["appointments"] == [appointment]
        # Recreate the client with the same credential to verify persistent authority.
        with httpx.Client(
            base_url=client.base_url, trust_env=False, timeout=20, cookies=client.cookies
        ) as refreshed:
            assert refreshed.get(base + "/booking").json()["appointments"] == [appointment]
        response = client.post(
            "/api/visitor-sessions", headers=headers, json={"store_code": "demo-hangzhou"}
        )
        response.raise_for_status()
        headers = {"X-CSRF-Token": response.json()["csrf_token"]}
        assert client.get(base + "/booking").status_code == 404
        assert client.post(path + "/confirm", headers=headers, json=confirm).status_code == 404
        client.post("/api/visitor-sessions/logout", headers=headers).raise_for_status()
        assert client.get(base + "/booking").status_code == 401
        print(
            {
                "proxy": "passed",
                "verification": "simulated-only",
                "appointment": "pending_store_confirmation",
                "draft_replay": "passed",
                "confirmation_replay": "passed",
                "reload": "passed",
                "cross_store": "denied",
                "logout": "denied",
                "input": "synthetic-only",
            }
        )


if __name__ == "__main__":
    main()
