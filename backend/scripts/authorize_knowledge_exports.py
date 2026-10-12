"""Record the user's all-current-knowledge authorization as exact, reviewable hashes."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from dotenv import set_key

from app.config import Settings
from app.model_gateway import fingerprint

PROBE_TEXT = "固定合成连通性检查：请仅回复连接成功。"
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "backend" / "data"


def record_authorization() -> None:
    hashes: set[str] = set(Settings().model_export_hashes)
    documents = 0
    for filename in (
        "synthetic_knowledge.json",
        "consultation_catalog.json",
        "consultation_expanded.json",
        "demo_consultation.json",
        "empathy_knowledge.json",
    ):
        items = json.loads((DATA / filename).read_text("utf-8"))
        for item in items:
            hashes.add(fingerprint(item["title"] + "\n" + item["content"]))
            documents += 1
    queries: set[str] = set()
    for filename in ("retrieval_cases.json", "retrieval_holdout.json"):
        for item in json.loads((DATA / filename).read_text("utf-8")):
            queries.add(item["question"])
    hashes.update(fingerprint(text) for text in queries)
    hashes.add(fingerprint(PROBE_TEXT))
    manifest = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "authorization": [
            "2026-10-11 user: 向量化出口范围现在是全部",
            "2026-10-12 user: 补齐虚构机构资料并模拟完整真实咨询场景",
            "2026-10-12 user: 加入情绪识别和共情安慰话术",
        ],
        "scope": "Current version-controlled knowledge dataset, synthetic evaluation and probe",
        "exclusions": ["customer identity", "business records", "future changed content"],
        "documents": documents,
        "synthetic_queries": len(queries),
        "hashes": sorted(hashes),
    }
    runtime = ROOT / "runtime"
    runtime.mkdir(exist_ok=True)
    (runtime / "model-export-authorization.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    set_key(
        ROOT / "backend" / ".env",
        "MA_MODEL_EXPORT_HASHES",
        json.dumps(sorted(hashes)),
        quote_mode="never",
    )
    print(
        json.dumps(
            {
                "documents": documents,
                "synthetic_queries": len(queries),
                "authorized_hashes": len(hashes),
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-user-authorization", action="store_true", required=True)
    parser.parse_args()
    record_authorization()
