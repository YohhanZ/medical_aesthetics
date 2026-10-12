"""Read-only, explicitly synthetic presentation material, never published knowledge."""

import json
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain import Actor, DomainError, Repository
from app.staff_booking import StaffBookingService

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "demo_materials.json"


class DemoMaterials:
    def __init__(self, repo: Repository, settings: Settings, actor: Actor, store: str) -> None:
        self.repo, self.settings, self.actor, self.store = repo, settings, actor, store

    def read(self, request_id: str) -> dict[str, Any]:
        if self.settings.environment == "production" or not self.settings.allow_simulated_data:
            raise DomainError("demo_materials_unavailable", 404)
        if self.actor.kind != "staff":
            raise DomainError("staff_required", 403)
        StaffBookingService(self.repo, self.settings, self.actor, self.store).grant("customer_read")
        row = self.repo.one(
            "SELECT public_code FROM store WHERE tenant_id=%s AND id=%s AND active AND simulated",
            (self.actor.tenant_id, self.store),
        )
        if not row:
            raise DomainError("demo_materials_unavailable", 404)
        data: dict[str, Any] = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        store = next((s for s in data["stores"] if s["code"] == row["public_code"]), None)
        if store is None:
            raise DomainError("demo_materials_unavailable", 404)
        self.repo.audit(self.actor, "demo_materials.read", self.store, request_id)
        return {
            **{
                key: data[key]
                for key in (
                    "schema_version",
                    "pack_id",
                    "title",
                    "version",
                    "simulated",
                    "disclosure",
                    "created_on",
                    "valid_until",
                    "rag_status",
                    "institution",
                    "suppliers",
                    "review_records",
                    "scripts",
                )
            },
            "store": store,
            **{
                key: [item for item in data[key] if item["store_code"] == row["public_code"]]
                for key in ("personnel", "services", "policies", "journeys")
            },
        }
