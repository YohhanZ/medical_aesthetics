from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import CheckViolation

from app.catalog import CatalogService
from app.config import Settings
from app.consultation_agent import ConsultationAgent
from app.db import transaction
from app.domain import Actor, DomainError
from app.knowledge_import import import_dataset
from app.seed import REVIEWER, STORE, TENANT, seed_store_locations
from app.services import KnowledgeService
from tests.conftest import visitor_headers
from tests.test_consultation_agent import FakeAnswer, agent, setup
from tests.test_knowledge_pipeline import TestGraph, drain


def publish_catalog(settings: Settings) -> None:
    import_dataset(settings, Path(__file__).parents[1] / "data/consultation_catalog.json")
    drain(settings, TestGraph())


def test_current_session_reloads_csrf_and_remains_same_visitor(client: TestClient) -> None:
    csrf = visitor_headers(client)
    first = client.get("/api/visitor-sessions/current").json()
    second = client.get("/api/visitor-sessions/current").json()
    assert first == second and first["csrf_token"] == csrf["X-CSRF-Token"]
    assert first["store_code"] == "demo-shanghai" and first["simulated"]
    client.cookies.delete("ma_visitor_csrf")
    renewed = client.get("/api/visitor-sessions/current").json()
    assert renewed["visitor_id"] == first["visitor_id"]
    assert renewed["csrf_token"] != first["csrf_token"]
    assert client.post("/api/threads", headers=csrf).status_code == 403
    assert (
        client.post("/api/threads", headers={"X-CSRF-Token": renewed["csrf_token"]}).status_code
        == 201
    )
    assert (
        client.post("/api/visitor-sessions", json={"store_code": "demo-hangzhou"}).status_code
        == 403
    )
    client.post("/api/visitor-sessions/logout", headers={"X-CSRF-Token": renewed["csrf_token"]})
    assert client.get("/api/visitor-sessions/current").status_code == 401
    assert "ma_visitor_csrf" not in client.cookies


def test_public_stores_excludes_disabled_and_production_simulation(
    client: TestClient, settings: Settings
) -> None:
    assert all(
        set(row)
        == {
            "code",
            "name",
            "simulated",
            "city",
            "address",
            "latitude",
            "longitude",
            "coordinate_system",
        }
        for row in client.get("/api/public/stores").json()["items"]
    )
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE store SET active=false WHERE public_code='demo-hangzhou'")
    assert len(client.get("/api/public/stores").json()["items"]) == 1
    from app.api import create_app

    production = settings.model_copy(update={"allow_simulated_data": False})
    with TestClient(create_app(production)) as restricted:
        assert restricted.get("/api/public/stores").json() == {"items": []}


def test_public_store_locations_are_optional_and_demo_seed_preserves_edits(
    client: TestClient, settings: Settings
) -> None:
    rows = client.get("/api/public/stores").json()["items"]
    shanghai = next(row for row in rows if row["code"] == "demo-shanghai")
    assert shanghai["latitude"] == 31.23 and shanghai["longitude"] == 121.47
    assert shanghai["coordinate_system"] == "WGS84"
    assert "模拟" in shanghai["address"] and shanghai["simulated"]
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE store SET latitude=31.1,longitude=121.1 WHERE id=%s", (STORE,))
        seed_store_locations(repo)
        assert repo.one("SELECT latitude FROM store WHERE id=%s", (STORE,))["latitude"] == 31.1
        repo.execute(
            "INSERT INTO store(id,tenant_id,public_code,name,simulated) VALUES(%s,%s,%s,%s,false)",
            (str(uuid4()), TENANT, "without-location", "尚未配置位置的门店"),
        )
    missing = next(
        row
        for row in client.get("/api/public/stores").json()["items"]
        if row["code"] == "without-location"
    )
    assert missing["latitude"] is None and missing["longitude"] is None


@pytest.mark.parametrize("latitude,longitude", [(91, 0), (0, 181), (None, 1), (1, None)])
def test_store_rejects_invalid_coordinate_pairs(
    settings: Settings, latitude: float | None, longitude: float | None
) -> None:
    with pytest.raises(CheckViolation), transaction(settings.database_url) as repo:
        repo.execute(
            "UPDATE store SET latitude=%s,longitude=%s WHERE id=%s",
            (latitude, longitude, STORE),
        )


def test_catalog_uses_approved_store_evidence_and_links_are_valid(
    client: TestClient, settings: Settings
) -> None:
    assert client.get("/api/catalog/projects").status_code == 401
    publish_catalog(settings)
    csrf = visitor_headers(client)
    items = client.get("/api/catalog/projects").json()["items"]
    assert len(items) == 10
    assert {item["category"] for item in items} == {"care", "medical"}
    assert all(
        item["simulated"] and item["detail_url"] == f"/#project/{item['id']}" for item in items
    )
    for item in items:
        assert (
            Path(__file__).parents[2] / "frontend/customer/public" / item["image_url"].lstrip("/")
        ).is_file()
        assert client.get(f"/api/catalog/projects/{item['id']}").json() == item
    assert client.get("/api/public/stores").json()["items"][0]["code"] == "demo-shanghai"
    client.post("/api/visitor-sessions", headers=csrf, json={"store_code": "demo-hangzhou"})
    assert client.get("/api/catalog/projects").json() == {"items": []}
    assert client.get(f"/api/catalog/projects/{items[0]['id']}").status_code == 404


def test_answer_project_links_replay_and_history_filter_withdrawn_directory(
    client: TestClient, settings: Settings
) -> None:
    publish_catalog(settings)
    store, _ = setup(client, settings)
    service = agent(store, settings, FakeAnswer())
    message_id = str(uuid4())
    result = service.send(message_id, "想了解基础补水护理")
    assert any(project["key"] == "hydration" for project in result["projects"])
    project_id = next(
        project["id"] for project in result["projects"] if project["key"] == "hydration"
    )
    with transaction(settings.database_url) as repo:
        KnowledgeService(repo, settings).withdraw(
            Actor(REVIEWER, TENANT, None, "staff", "test"), STORE, project_id, str(uuid4())
        )
    assert all(
        project["id"] != project_id
        for project in service.send(message_id, "想了解基础补水护理")["projects"]
    )
    assert client.get(f"/api/catalog/projects/{project_id}").status_code == 404
    rows = service.history(100, 0, True)
    assert all(project["id"] != project_id for project in rows[-1]["result"]["projects"])
    medical = ConsultationAgent(store).send(str(uuid4()), "我怀孕了，能做水光吗")
    assert medical["projects"] == []


def test_threads_and_recent_history_are_owned_and_chronological(
    client: TestClient, settings: Settings
) -> None:
    store, csrf = setup(client, settings)
    service = ConsultationAgent(store)
    for _ in range(4):
        service.send(str(uuid4()), "你好")
    rows = client.get(f"/api/threads/{store.thread_id}/messages?recent=true&limit=4").json()[
        "items"
    ]
    assert [row["role"] for row in rows] == ["user", "assistant", "user", "assistant"]
    assert len({row["message_id"] for row in rows}) == 2
    assert client.get("/api/threads").json()["items"][0]["thread_id"] == store.thread_id
    client.post("/api/visitor-sessions/logout", headers=csrf)
    visitor_headers(client)
    assert client.get("/api/threads").json() == {"items": []}
    assert client.get(f"/api/threads/{store.thread_id}/messages?recent=true").status_code == 404


def test_project_link_requires_query_relevance_not_only_a_retrieved_citation(
    client: TestClient, settings: Settings
) -> None:
    from app.retrieval import PostgresEvidenceReader

    publish_catalog(settings)
    store, _ = setup(client, settings)
    service = CatalogService(PostgresEvidenceReader(settings))
    ids = [row["id"] for row in service.projects(store.actor)]
    assert service.related(store.actor, "到店咨询前需要准备什么", ids) == []
    related = service.related(store.actor, "想了解补水和保湿", [])
    assert [row["key"] for row in service.projects(store.actor) if row["id"] in related] == [
        "hydration"
    ]


def test_catalog_fails_closed_when_session_revoked_mid_metadata_read(
    client: TestClient, settings: Settings
) -> None:
    from app.retrieval import PostgresEvidenceReader
    from app.services import IdentityService

    publish_catalog(settings)
    store, _ = setup(client, settings)

    class RevokingReader(PostgresEvidenceReader):
        def details(self, ids: list[str]):
            result = super().details(ids)
            with transaction(settings.database_url) as repo:
                IdentityService(repo, settings).revoke(store.actor)
            return result

    with pytest.raises(DomainError) as error:
        CatalogService(RevokingReader(settings)).projects(store.actor)
    assert error.value.code == "unauthenticated"
