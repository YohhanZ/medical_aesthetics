import json
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import transaction
from app.demo_materials import DATA_PATH, DemoMaterials
from app.domain import Actor, DomainError
from app.seed import CONSULTANT, OTHER_STORE, STORE, TENANT
from app.services import IdentityService
from tests.conftest import staff_headers, visitor_headers


def test_pack_is_consistent_and_cannot_imply_actual_verification() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert data["simulated"] and data["rag_status"] == "presentation_only_not_published"
    assert (len(data["stores"]), len(data["personnel"]), len(data["services"])) == (2, 10, 24)
    codes = {s["code"] for s in data["stores"]}
    assert data["institution"]["medical_license_number"] is None
    assert data["institution"]["registration_number"] is None
    for key in ("personnel", "services", "policies", "journeys"):
        assert len({r["id"] for r in data[key]}) == len(data[key])
        assert all(r["store_code"] in codes and r["simulated"] for r in data[key])
    for service in data["services"]:
        assert 0 <= service["demo_price_cny"] <= service["list_price_cny"]
        assert service["treatment_price_cny"] is None and service["registration_number"] is None
        if service["category"] == "医疗美容咨询":
            assert service["demo_price_cny"] == 0 and "不含" in service["included"]
    assert all(
        p["license_number"] is None and p["actual_account"] is None for p in data["personnel"]
    )
    suppliers = {s["id"] for s in data["suppliers"]}
    for review in data["review_records"]:
        assert review["supplier_id"] in suppliers and review["simulated"]
        assert review["prepared_by"] != review["reviewed_by"]
        assert review["actual_result"] == "未验收"
        assert review["evidence_reference"].startswith("SIM-")


def test_staff_scope_projection_audit_and_revocation(
    client: TestClient, settings: Settings
) -> None:
    headers = staff_headers(client, "demo-consultant")
    result = client.get(f"/api/stores/{STORE}/demo-materials", headers=headers)
    assert result.status_code == 200, result.text
    pack = result.json()
    assert pack["store"]["code"] == "demo-shanghai" and "stores" not in pack
    assert len(pack["personnel"]) == 5 and len(pack["services"]) == 12
    assert all(p["store_code"] == "demo-shanghai" for p in pack["personnel"])
    assert "demo-hangzhou" not in result.text
    assert (
        client.get(f"/api/stores/{OTHER_STORE}/demo-materials", headers=headers).status_code == 403
    )
    for user in ("demo-author", "demo-operator", "demo-platform-admin"):
        assert (
            client.get(
                f"/api/stores/{STORE}/demo-materials", headers=staff_headers(client, user)
            ).status_code
            == 403
        )
    assert client.get(f"/api/stores/{STORE}/demo-materials").status_code == 401
    visitor_headers(client)
    assert client.get(f"/api/stores/{STORE}/demo-materials").status_code == 401
    with transaction(settings.database_url) as repo:
        assert repo.one("SELECT id FROM audit WHERE action='demo_materials.read'")
        repo.execute(
            "DELETE FROM store_grant WHERE staff_id=%s AND permission='customer_read'",
            (CONSULTANT,),
        )
    assert client.get(f"/api/stores/{STORE}/demo-materials", headers=headers).status_code == 403


def test_only_simulated_active_store_and_environment(settings: Settings) -> None:
    with transaction(settings.database_url) as repo:
        login = IdentityService(repo, settings).login(
            "demo-consultant", "Synthetic-test-password-2026!", "local", str(uuid4())
        )
        actor = IdentityService(repo, settings).authenticate(login["access_token"], "staff")
        for changes in ({"environment": "production"}, {"allow_simulated_data": False}):
            guarded = settings.model_copy(update=changes)
            with pytest.raises(DomainError, match="demo_materials_unavailable"):
                DemoMaterials(repo, guarded, actor, STORE).read(str(uuid4()))
        repo.execute("UPDATE store SET simulated=false WHERE id=%s", (STORE,))
        with pytest.raises(DomainError, match="demo_materials_unavailable"):
            DemoMaterials(repo, settings, actor, STORE).read(str(uuid4()))
        visitor = Actor(str(uuid4()), TENANT, STORE, "visitor", str(uuid4()))
        with pytest.raises(DomainError, match="staff_required"):
            DemoMaterials(repo, settings, visitor, STORE).read(str(uuid4()))


def test_materials_read_audit_failure_is_not_a_successful_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db import PostgresRepository

    headers = staff_headers(client, "demo-consultant")
    original = PostgresRepository.audit

    def audit(self: PostgresRepository, *args: Any) -> None:
        if args[1] == "demo_materials.read":
            raise DomainError("audit_unavailable", 503)
        original(self, *args)

    monkeypatch.setattr(PostgresRepository, "audit", audit)
    result = client.get(f"/api/stores/{STORE}/demo-materials", headers=headers)
    assert result.status_code == 503 and "services" not in result.json()
