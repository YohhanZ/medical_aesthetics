"""Body-area questions must switch topics without borrowing the previous project."""

import json
from pathlib import Path

import pytest

from app.agent_policy import classify
from app.catalog import CatalogService
from app.conversation_context import PublicTopics


def demo_projects():
    rows = json.loads(
        (Path(__file__).parents[1] / "data/demo_consultation.json").read_text("utf-8")
    )
    return [
        {
            "key": row["knowledge_key"].removeprefix("catalog-"),
            "id": row["knowledge_key"],
            "title": row["title"],
            "topics": row["details"]["topics"],
        }
        for row in rows
        if row["knowledge_key"].startswith("catalog-")
    ]


@pytest.mark.parametrize(
    "question,expected",
    [
        ("我想了解一下清洁项目", ["cleansing"]),
        ("背部项目有哪些", ["back-care"]),
        ("手部项目有哪些", ["hand-care"]),
        ("眼周有哪些护理", ["eye-care"]),
        ("颈部项目有哪些", ["neck-care"]),
        ("背部和手部护理有什么区别", ["back-care", "hand-care"]),
        ("生活护理有哪些", []),
        ("医学美容咨询流程是什么", []),
        ("背部项目有哪些，我有点紧张，想了解一下", ["back-care"]),
    ],
)
def test_public_body_area_topics_and_local_emotional_projection(question, expected):
    topics = PublicTopics(demo_projects())
    assert topics.match(classify(question, True)["question"]) == expected


def test_related_cards_use_the_same_specific_project_matcher():
    class ScopedCatalog(CatalogService):
        def projects(self, actor):
            return demo_projects()

    catalog = ScopedCatalog(None)
    assert catalog.related(None, "背部项目有哪些", ["catalog-cleansing"]) == [
        "catalog-back-care"
    ]
