import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.db import transaction
from app.domain import Actor, Repository, now
from app.security import password_hash
from app.services import KnowledgeService

TENANT = "00000000-0000-4000-8000-000000000001"
STORE = "00000000-0000-4000-8000-000000000011"
OTHER_STORE = "00000000-0000-4000-8000-000000000012"
AUTHOR = "00000000-0000-4000-8000-000000000021"
REVIEWER = "00000000-0000-4000-8000-000000000022"
ADMIN = "00000000-0000-4000-8000-000000000023"
OPERATOR = "00000000-0000-4000-8000-000000000024"
CONSULTANT = "00000000-0000-4000-8000-000000000025"


def seed_consultant(repo: Repository, password: str) -> None:
    # New isolated simulated role; existing credentials and revoked grants remain unchanged.
    if repo.one("SELECT id FROM staff WHERE id=%s", (CONSULTANT,)):
        return
    repo.execute(
        "INSERT INTO staff(id,tenant_id,username,password_hash,simulated) VALUES(%s,%s,%s,%s,true)",
        (CONSULTANT, TENANT, "demo-consultant", password_hash(password)),
    )
    for permission in ("appointment_read", "customer_read", "customer_manage"):
        repo.execute(
            "INSERT INTO store_grant(tenant_id,staff_id,store_id,permission) VALUES(%s,%s,%s,%s)",
            (TENANT, CONSULTANT, STORE, permission),
        )


def seed_booking_operator(repo: Repository, password: str) -> None:
    # A separate simulated operator, never broaden author/reviewer/admin permissions.
    # Existing operator credentials and revoked grants are deliberately preserved.
    if repo.one("SELECT id FROM staff WHERE id=%s", (OPERATOR,)):
        return
    repo.execute(
        "INSERT INTO staff(id,tenant_id,username,password_hash,simulated) VALUES(%s,%s,%s,%s,true)",
        (OPERATOR, TENANT, "demo-operator", password_hash(password)),
    )
    for permission in ("appointment_read", "appointment_manage", "appointment_contact"):
        repo.execute(
            "INSERT INTO store_grant(tenant_id,staff_id,store_id,permission) VALUES(%s,%s,%s,%s)",
            (TENANT, OPERATOR, STORE, permission),
        )


def seed(settings: Settings, password: str) -> dict[str, Any]:
    if settings.environment == "production" or not settings.allow_simulated_data:
        raise RuntimeError("Synthetic seed requires explicit nonproduction simulation setting")
    if len(password) < 16:
        raise RuntimeError("Use a local seed password of at least 16 characters")
    with transaction(settings.database_url) as repo:
        repo.execute("SELECT pg_advisory_xact_lock(871230012)")
        existing = repo.one("SELECT id FROM tenant WHERE id=%s", (TENANT,))
        if existing:
            seed_booking_operator(repo, password)
            seed_consultant(repo, password)
            return {"status": "already_seeded"}
        repo.execute(
            "INSERT INTO tenant(id,name,simulated) VALUES(%s,%s,true)",
            (TENANT, "虚构演练机构（非美丽田园真实运营资料）"),
        )
        for store_id, code, name in [
            (STORE, "demo-shanghai", "模拟上海体验店"),
            (OTHER_STORE, "demo-hangzhou", "模拟杭州体验店"),
        ]:
            repo.execute(
                "INSERT INTO store(id,tenant_id,public_code,name,simulated) "
                "VALUES(%s,%s,%s,%s,true)",
                (store_id, TENANT, code, name),
            )
        for staff_id, username in [
            (AUTHOR, "demo-author"),
            (REVIEWER, "demo-reviewer"),
            (ADMIN, "demo-platform-admin"),
        ]:
            repo.execute(
                "INSERT INTO staff(id,tenant_id,username,password_hash,simulated) "
                "VALUES(%s,%s,%s,%s,true)",
                (staff_id, TENANT, username, password_hash(password)),
            )
        # Platform admin deliberately has no store grants or customer access.
        for staff_id in (AUTHOR, REVIEWER):
            for permission in ("knowledge_author", "knowledge_review", "knowledge_publish"):
                repo.execute(
                    "INSERT INTO store_grant(tenant_id,staff_id,store_id,permission) "
                    "VALUES(%s,%s,%s,%s)",
                    (TENANT, staff_id, STORE, permission),
                )
        seed_booking_operator(repo, password)
        seed_consultant(repo, password)
        author = Actor(AUTHOR, TENANT, None, "staff", "seed")
        reviewer = Actor(REVIEWER, TENANT, None, "staff", "seed")
        service = KnowledgeService(repo, settings)
        path = Path(__file__).parents[1] / "data" / "synthetic_knowledge.json"
        items = json.loads(path.read_text(encoding="utf-8"))
        for item in items:
            item["simulated"] = True
            item["valid_until"] = now() + timedelta(days=90)
            created = service.create(author, STORE, item, str(uuid4()))
            if item["category"] != "medical":
                service.review(
                    reviewer,
                    STORE,
                    created["version_id"],
                    True,
                    "仅用于本地模拟运营演练，独立账号复核，不是真实机构批准",
                    str(uuid4()),
                )
                service.publish(reviewer, STORE, created["version_id"], str(uuid4()))
        return {"status": "seeded", "items": len(items), "simulated": True}


if __name__ == "__main__":
    result = seed(Settings(), os.environ.get("M1_SEED_PASSWORD", ""))
    print(json.dumps(result, ensure_ascii=False))
