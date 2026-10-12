"""Public project views derived from currently approved store knowledge versions."""

import re
from typing import Any

from app.domain import Actor, DomainError
from app.retrieval import EvidenceReader

GENERIC_TOPICS = {"生活美容护理", "生活护理", "医学美容咨询", "咨询服务", "医疗美容", "美容护理"}
PROJECT_ALIASES = {
    "hydration": ["补水", "保湿", "水润"],
    "cleansing": ["清洁"],
    "relaxation": ["舒缓"],
    "assessment": ["皮肤检测", "皮肤状态"],
}


class CatalogService:
    def __init__(self, reader: EvidenceReader) -> None:
        self.reader = reader

    def projects(self, actor: Actor) -> list[dict[str, Any]]:
        catalog = {
            str(row["id"]): row
            for row in self.reader.evidence(actor)
            if row["knowledge_key"].startswith("catalog-")
        }
        details = self.reader.details(list(catalog)) if catalog else []
        rows = []
        for detail in details:
            row = catalog[str(detail["version_id"])]
            entities = detail.get("entities", [])
            project = next((item for item in entities if item["kind"] == "Project"), None)
            if not project:
                continue
            medical = "医学美容咨询" in detail["topics"]
            key = project["key"]
            scene = "medical-consultation" if medical else "care-consultation"
            if key == "hydration":
                scene = "hydration-care"
            elif key in ("assessment", "texture-consultation"):
                scene = "skin-assessment"
            rows.append(
                {
                    "id": str(row["id"]),
                    "key": key,
                    "title": project["name"],
                    "category": "medical" if medical else "care",
                    "summary": row["content"][:180],
                    "description": row["content"],
                    "topics": detail["topics"],
                    "image_url": f"/images/{scene}-v2.jpg",
                    "image_alt": "AI 场景示意：顾客与专业人员了解护理或医美服务",
                    "image_provenance": "AI 场景示意，不代表真实顾客、医生、设备或治疗效果",
                    "detail_url": f"/#project/{row['id']}",
                    "source": row["source"],
                    "version": row["version"],
                    "simulated": row["simulated"],
                    "valid_until": row["valid_until"],
                }
            )
        allowed = {str(row["id"]) for row in self.reader.evidence(actor)}
        return sorted((row for row in rows if row["id"] in allowed), key=lambda row: row["key"])

    def get(self, actor: Actor, project_id: str) -> dict[str, Any]:
        project = next((row for row in self.projects(actor) if row["id"] == project_id), None)
        if not project:
            raise DomainError("project_unavailable", 404)
        return project

    def related(self, actor: Actor, question: str, evidence_ids: list[str]) -> list[str]:
        query = question.lower()
        ranked = []
        for project in self.projects(actor):
            score = sum(
                len(topic)
                for topic in project["topics"] + PROJECT_ALIASES.get(project["key"], [])
                if topic not in GENERIC_TOPICS and len(topic) >= 2 and topic.lower() in query
            )
            if score:
                score += 10 if project["id"] in evidence_ids else 0
                ranked.append((score, project["key"], project["id"]))
        return [item[2] for item in sorted(ranked, key=lambda row: (-row[0], row[1]))[:3]]


def related_query(question: str, previous: list[str]) -> str:
    if previous and re.match(r"^(那|这个|它|这种|那个|继续|还有)", question):
        return previous[-1] + "\n" + question
    return question
