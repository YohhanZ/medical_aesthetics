"""Simulation knowledge must be useful, sourced, independent and impossible in production."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent_policy import classify
from app.config import Settings
from app.conversation_context import PublicTopics
from app.db import transaction
from app.domain import Actor, DomainError
from app.knowledge_import import DatasetItem, import_dataset
from app.knowledge_types import KnowledgeDetails
from app.knowledge_worker import ProjectionWorker, eligible
from app.retrieval import PostgresEvidenceReader
from app.seed import AUTHOR, STORE, TENANT
from app.services import KnowledgeService
from tests.test_knowledge_pipeline import TestEmbedding, TestGraph, visitor_actor

DATA = Path(__file__).parents[1] / "data" / "demo_consultation.json"


def drain_demo(settings: Settings) -> None:
    graph = TestGraph()
    worker = ProjectionWorker(settings, graph, TestEmbedding(), graph.vectors)
    for _ in range(100):
        result = worker.run_once()
        if result["status"] == "idle":
            return
        assert result["status"] in ("published", "removed"), result
    raise AssertionError("Demo outbox did not finish")


def test_dataset_has_concrete_content_and_separate_education_scope() -> None:
    rows = [DatasetItem.model_validate(r) for r in json.loads(DATA.read_text("utf-8"))]
    assert len(rows) == len({r.knowledge_key for r in rows}) == 70
    assert sum(r.category == "medical" for r in rows) == 22
    assert sum(r.knowledge_key.startswith("catalog-") for r in rows) == 30
    assert sum(r.category == "communication" for r in rows) == 10
    hydration = next(r for r in rows if r.knowledge_key == "catalog-hydration")
    assert all(t in hydration.content for t in ("60分钟", "298元", "面膜", "精华"))
    assert "仅提供了解入口" not in hydration.content
    for row in rows:
        if row.category == "medical":
            assert row.details.review_scope == "demo_education"
            assert row.details.source_urls and row.details.source_date
            assert "虚构" in row.source and "模拟" in row.source
        if row.category == "communication":
            assert row.details.audience == "internal"


def test_default_mode_keeps_demo_medical_pending(settings: Settings) -> None:
    imported = import_dataset(settings, DATA)
    assert imported["medical_pending"] == 22
    with transaction(settings.database_url) as repo:
        row = repo.one("SELECT * FROM knowledge_version WHERE knowledge_key='catalog-ipl'")
        assert row and row["status"] == "draft"
        assert eligible(repo, str(row["id"]), True) is None


def test_explicit_demo_publishes_and_rechecks_source_scope(
    client: TestClient, settings: Settings
) -> None:
    demo = settings.model_copy(update={"demo_medical_education": True})
    assert import_dataset(demo, DATA)["medical_pending"] == 0
    drain_demo(demo)
    actor = visitor_actor(client, demo)
    reader = PostgresEvidenceReader(demo)
    current = reader.evidence(actor)
    ipl = next(r for r in current if r["knowledge_key"] == "catalog-ipl")
    assert ipl["review_scope"] == "demo_education" and ipl["simulated"]
    assert "强脉冲光" in ipl["content"]
    assert not any(r["knowledge_key"].startswith("demo-sales-") for r in current)
    with transaction(settings.database_url) as repo:
        record = repo.one(
            "SELECT k.author_id,r.reviewer_id,r.simulated,r.reason FROM knowledge_version k "
            "JOIN knowledge_review r ON r.version_id=k.id WHERE k.id=%s",
            (ipl["id"],),
        )
        assert record and record["author_id"] != record["reviewer_id"]
        assert record["simulated"] and "不代表真实医学批准" in record["reason"]
        assert eligible(repo, str(ipl["id"]), True) is None
        assert eligible(repo, str(ipl["id"]), True, True)
    assert not any(
        r["knowledge_key"] == "catalog-ipl"
        for r in PostgresEvidenceReader(settings).evidence(actor)
    )
    assert import_dataset(demo, DATA)["skipped"] == 70
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE knowledge_version SET status='withdrawn' WHERE id=%s", (ipl["id"],))
    assert not any(r["id"] == ipl["id"] for r in reader.evidence(actor))


def test_demo_does_not_allow_author_self_review_or_old_medical_drafts(settings: Settings) -> None:
    demo = settings.model_copy(update={"demo_medical_education": True})
    # Import with the normal gate first so medical items remain drafts.
    import_dataset(settings, DATA)
    with transaction(settings.database_url) as repo:
        row = repo.one("SELECT id FROM knowledge_version WHERE knowledge_key='catalog-ipl'")
        assert row
        with pytest.raises(DomainError, match="independent_review_required"):
            KnowledgeService(repo, demo).review(
                Actor(AUTHOR, TENANT, None, "staff", "test"),
                STORE,
                str(row["id"]),
                True,
                "复核",
                "test",
            )
        old = repo.one(
            "SELECT * FROM knowledge_version WHERE category='medical' "
            "AND knowledge_key<>'catalog-ipl' ORDER BY created_at LIMIT 1"
        )
        assert old
        # Seed's old unscoped clinical item cannot acquire a simulated approval.
        assert not KnowledgeService(repo, demo).demo_medical_version(old)


def test_production_and_unmarked_source_cannot_enable_demo_education() -> None:
    with pytest.raises(ValidationError, match="nonproduction"):
        Settings(
            _env_file=None,
            database_url="postgresql://unused",
            environment="production",
            allow_simulated_data=True,
            demo_medical_education=True,
        )
    with pytest.raises(ValidationError, match="nonproduction"):
        Settings(_env_file=None, database_url="postgresql://unused", demo_medical_education=True)
    with pytest.raises(ValidationError, match="dated public sources"):
        KnowledgeDetails(review_scope="demo_education")


def test_topic_price_followup_and_overlapping_project_names() -> None:
    assert classify("激光脱毛是什么？是不是一次就完成？")["intent"] == "information"
    projects: list[dict[str, Any]] = [
        {"key": key, "id": key, "title": title}
        for key, title in (
            ("hydration", "基础补水护理"),
            ("rf", "射频紧致咨询"),
            ("rf-microneedling-overview", "射频微针咨询"),
            ("microneedling-overview", "微针项目咨询"),
            ("ultrasound", "超声紧致咨询"),
            ("hair-removal-overview", "激光脱毛咨询"),
            ("laser-overview", "激光项目咨询"),
        )
    ]
    topics = PublicTopics(projects)
    assert topics.query("那多少钱？", ["hydration"], []) == "基础补水护理\n那多少钱？"
    assert topics.match("射频微针是什么？") == ["rf-microneedling-overview"]
    assert set(topics.match("微针和射频微针的区别")) == {
        "microneedling-overview",
        "rf-microneedling-overview",
    }
    assert topics.match("超声炮怎么了解？") == ["ultrasound"]
    assert topics.match("激光脱毛是什么？") == ["hair-removal-overview"]
    allowed = {"hydration": {"id": "hydration", "knowledge_key": "catalog-hydration"}}
    assert topics.rank("那多少钱？", ["hydration"], [], allowed)[0]["id"] == "hydration"


@pytest.mark.parametrize(
    "question,reason",
    [
        ("光子一般有哪些风险，比如过敏和疼痛？", ""),
        ("我过敏，光子一般有哪些风险？", "personal_medical"),
        ("朋友做完光子疼痛，一般怎么处理？", "personal_medical"),
    ],
)
def test_general_education_never_turns_personal_symptoms_into_public_data(
    question: str, reason: str
) -> None:
    assert classify(question)["reason"] == reason
