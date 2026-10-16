"""Public project views derived from currently approved store knowledge versions."""

import re
from typing import Any

from app.conversation_context import PublicTopics
from app.domain import Actor, DomainError
from app.retrieval import EvidenceReader


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
        topics = PublicTopics(self.projects(actor))
        # Cards and retrieval must agree on explicit topics; a retrieved citation
        # from another service cannot turn into a recommendation by itself.
        return [topics.projects[key]["id"] for key in topics.match(question)]


def related_query(question: str, previous: list[str]) -> str:
    if previous and re.match(r"^(那|这个|它|这种|那个|继续|还有)", question):
        return previous[-1] + "\n" + question
    return question
