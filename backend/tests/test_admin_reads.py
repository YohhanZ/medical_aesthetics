from fastapi.testclient import TestClient

from app.seed import OTHER_STORE, STORE
from tests.conftest import staff_headers, visitor_headers


def test_profile_returns_only_explicit_store_grants(client: TestClient) -> None:
    profile = client.get("/api/staff/me", headers=staff_headers(client)).json()
    assert [str(store["id"]) for store in profile["stores"]] == [STORE]
    assert "password_hash" not in profile and "tenant_id" not in profile
    admin = client.get("/api/staff/me", headers=staff_headers(client, "demo-platform-admin"))
    assert admin.status_code == 200 and admin.json()["stores"] == []


def test_knowledge_reads_are_scoped_and_paginated(client: TestClient) -> None:
    headers = staff_headers(client)
    first = client.get(f"/api/stores/{STORE}/knowledge?limit=2", headers=headers)
    second = client.get(f"/api/stores/{STORE}/knowledge?limit=2&offset=2", headers=headers)
    assert first.status_code == 200 and first.json()["total"] == 6
    assert len(first.json()["items"]) == 2
    assert {item["id"] for item in first.json()["items"]}.isdisjoint(
        {item["id"] for item in second.json()["items"]}
    )
    assert client.get(f"/api/stores/{OTHER_STORE}/knowledge", headers=headers).status_code == 403
    admin = staff_headers(client, "demo-platform-admin")
    assert client.get(f"/api/stores/{STORE}/knowledge", headers=admin).status_code == 403
    assert (
        client.get(f"/api/stores/{STORE}/knowledge?limit=101", headers=headers).status_code == 422
    )


def test_visitor_cannot_read_staff_profile_or_unpublished_knowledge(client: TestClient) -> None:
    visitor_headers(client)
    bearer = {"Authorization": f"Bearer {client.cookies.get('ma_visitor')}"}
    assert client.get("/api/staff/me", headers=bearer).status_code == 403
    assert client.get(f"/api/stores/{STORE}/knowledge", headers=bearer).status_code == 403
