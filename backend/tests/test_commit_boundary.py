from fastapi.testclient import TestClient

from app.config import Settings
from app.db import transaction
from tests.conftest import visitor_headers


def test_deferred_commit_failure_never_sends_success_cookie(
    client: TestClient, settings: Settings
) -> None:
    # A real deferred Postgres failure exercises the commit boundary, not a mock return value.
    with transaction(settings.database_url) as repo:
        repo.execute(
            "CREATE FUNCTION test_commit_failure() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'synthetic deferred failure' USING ERRCODE='40001'; END $$"
        )
        repo.execute(
            "CREATE CONSTRAINT TRIGGER test_commit_failure AFTER INSERT ON visitor "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION test_commit_failure()"
        )
    try:
        response = client.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"})
        assert response.status_code == 503
        assert "set-cookie" not in response.headers
        assert "synthetic deferred failure" not in response.text
        with transaction(settings.database_url) as repo:
            assert repo.one("SELECT count(*) AS count FROM visitor") == {"count": 0}
    finally:
        with transaction(settings.database_url) as repo:
            repo.execute("DROP TRIGGER test_commit_failure ON visitor")
            repo.execute("DROP FUNCTION test_commit_failure()")


def test_expired_cookie_can_start_new_session(client: TestClient, settings: Settings) -> None:
    visitor_headers(client)
    with transaction(settings.database_url) as repo:
        repo.execute("UPDATE auth_session SET expires_at=now()-interval '1 second'")
    response = client.post("/api/visitor-sessions", json={"store_code": "demo-shanghai"})
    assert response.status_code == 201
