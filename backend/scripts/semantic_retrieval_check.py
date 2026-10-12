"""Real Qwen/Milvus hybrid recall on 31 synthetic holdout queries; never customer data."""

import json
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def evaluate() -> None:
    cases = json.loads((ROOT / "backend/data/retrieval_holdout.json").read_text("utf-8"))
    methods: Counter[str] = Counter()
    hits, missed = 0, []
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=40, trust_env=False) as client:
        session = client.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"})
        assert session.status_code == 201
        csrf = {"X-CSRF-Token": session.json()["csrf_token"]}
        try:
            for case in cases:
                response = client.post(
                    "/api/knowledge/search", headers=csrf, json={"question": case["question"]}
                )
                assert response.status_code == 200
                result = response.json()
                methods[result["method"]] += 1
                keys = [item["knowledge_key"] for item in result["items"]]
                assert all(not key.startswith(("medical-", "sales-", "dialog-")) for key in keys)
                if case["expected_key"] in keys:
                    hits += 1
                else:
                    missed.append(case["expected_key"])
        finally:
            assert client.post("/api/visitor-sessions/logout", headers=csrf).status_code == 200
    report = {
        "cases": len(cases),
        "hits_at_5": hits,
        "recall_at_5": hits / len(cases),
        "methods": dict(methods),
        "missed_keys": missed,
        "scope": "local synthetic hybrid retrieval; not clinical or production performance",
    }
    (ROOT / "runtime/semantic-retrieval-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    assert methods["hybrid"] == len(cases), (
        "Real semantic retrieval was not available for every case"
    )
    assert hits / len(cases) >= 0.8, "Synthetic holdout recall below 80%"


if __name__ == "__main__":
    evaluate()
