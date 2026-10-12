"""Versioned, repeatable local synthetic dataset import through existing permission services."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.db import transaction
from app.domain import Actor, now
from app.knowledge_types import KnowledgeDetails
from app.model_gateway import fingerprint
from app.seed import AUTHOR, REVIEWER, STORE, TENANT
from app.services import KnowledgeService


class DatasetItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_key: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    category: Literal["operational", "communication", "medical"]
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=12000)
    source: str = Field(min_length=1, max_length=1000)
    details: KnowledgeDetails


def import_dataset(settings: Settings, path: Path) -> dict[str, Any]:
    if settings.environment == "production" or not settings.allow_simulated_data:
        raise RuntimeError("Synthetic import requires explicit nonproduction simulation setting")
    items = [DatasetItem.model_validate(item) for item in json.loads(path.read_text("utf-8"))]
    if len({item.knowledge_key for item in items}) != len(items):
        raise ValueError("Duplicate dataset keys")
    created, skipped, pending = 0, 0, 0
    with transaction(settings.database_url) as repo:
        repo.execute("SELECT pg_advisory_xact_lock(871230014)")
        service = KnowledgeService(repo, settings)
        author = Actor(AUTHOR, TENANT, None, "staff", "dataset-import")
        reviewer = Actor(REVIEWER, TENANT, None, "staff", "dataset-import")
        service.grant(author, STORE, "knowledge_author")
        service.grant(reviewer, STORE, "knowledge_review")
        for item in items:
            # Explicit source fields keep existing import digests stable as schemas gain defaults.
            payload = item.model_dump(mode="json", exclude_unset=True)
            content_hash = fingerprint(json.dumps(payload, sort_keys=True, ensure_ascii=False))
            existing = repo.one(
                "SELECT version_id FROM knowledge_import WHERE tenant_id=%s AND store_id=%s "
                "AND knowledge_key=%s AND content_hash=%s",
                (TENANT, STORE, item.knowledge_key, content_hash),
            )
            if existing:
                skipped += 1
                continue
            payload.update(simulated=True, valid_until=now() + timedelta(days=90))
            result = service.create(author, STORE, payload, str(uuid4()))
            repo.execute(
                "INSERT INTO knowledge_import(tenant_id,store_id,knowledge_key,content_hash,"
                "version_id) VALUES(%s,%s,%s,%s,%s)",
                (TENANT, STORE, item.knowledge_key, content_hash, result["version_id"]),
            )
            created += 1
            if item.category == "medical" and not (
                settings.demo_medical_enabled and item.details.review_scope == "demo_education"
            ):
                pending += 1
                continue
            service.review(
                reviewer,
                STORE,
                result["version_id"],
                True,
                "独立开发账号复核公开来源及合成演示设定；非真实机构或医学批准",
                str(uuid4()),
            )
            service.publish(reviewer, STORE, result["version_id"], str(uuid4()))
    return {"created": created, "skipped": skipped, "medical_pending": pending, "simulated": True}


if __name__ == "__main__":
    for name in (
        "consultation_catalog.json",
        "consultation_expanded.json",
        "demo_consultation.json",
        "empathy_knowledge.json",
    ):
        path = Path(__file__).parents[1] / "data" / name
        print(json.dumps({"dataset": name, **import_dataset(Settings(), path)}, ensure_ascii=False))
