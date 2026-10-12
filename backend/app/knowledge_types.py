from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
    kind: Literal["Project", "Category", "Concern", "Strategy", "Scenario"]
    name: str = Field(min_length=1, max_length=100)


class Relation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    kind: Literal["BELONGS_TO", "RELATED_TO", "APPLIES_TO"]


class KnowledgeDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audience: Literal["public", "internal"] = "public"
    topics: list[str] = Field(default_factory=list, max_length=30)
    entities: list[Entity] = Field(default_factory=list, max_length=30)
    relations: list[Relation] = Field(default_factory=list, max_length=50)
    questions: list[str] = Field(default_factory=list, max_length=8)
    stage: Literal[
        "awareness", "needs", "comparison", "visit_interest", "confirmation", "after_visit"
    ] = "awareness"
    allowed_actions: list[
        Literal["answer", "ask_clarification", "offer_visit", "handoff", "stop_invitation"]
    ] = ["answer"]
    handoff_reasons: list[str] = Field(default_factory=list, max_length=10)
    source_type: Literal["synthetic", "official_public", "authoritative_medical"] = "synthetic"
    source_urls: list[HttpUrl] = Field(default_factory=list, max_length=5)
    source_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    jurisdiction: Literal["CN", "US", "global", "unverified"] = "unverified"
    review_scope: Literal["standard", "demo_education"] = "standard"

    @model_validator(mode="after")
    def references(self) -> Self:
        if self.review_scope == "demo_education" and (
            self.audience != "public"
            or self.source_type == "synthetic"
            or not self.source_urls
            or not self.source_date
        ):
            raise ValueError("demo education requires dated public sources and public audience")
        keys = [entity.key for entity in self.entities]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate entity keys")
        if any(not topic.strip() or len(topic) > 80 for topic in self.topics):
            raise ValueError("invalid topic")
        if any(not question.strip() or len(question) > 300 for question in self.questions):
            raise ValueError("invalid question variant")
        if any(not reason.strip() or len(reason) > 200 for reason in self.handoff_reasons):
            raise ValueError("invalid handoff reason")
        if self.source_type != "synthetic" and (not self.source_urls or not self.source_date):
            raise ValueError("public source requires URL and retrieval date")
        kinds = {entity.key: entity.kind for entity in self.entities}
        allowed = {
            "BELONGS_TO": ("Project", "Category"),
            "RELATED_TO": ("Project", "Concern"),
            "APPLIES_TO": ("Strategy", "Scenario"),
        }
        for relation in self.relations:
            if (kinds.get(relation.source), kinds.get(relation.target)) != allowed[relation.kind]:
                raise ValueError("invalid relation endpoints")
        return self
