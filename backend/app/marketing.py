"""Store-scoped marketing jobs. Prompts never read customer records or credentials."""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import Settings
from app.domain import Actor, DomainError, Repository
from app.staff_booking import StaffBookingService

IMAGE_MODEL = "Kwai-Kolors/Kolors"
VIDEO_MODEL = "wan2.2-t2v-plus"


class MarketingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    kind: Literal["image", "video"]
    brand: str = Field(default="美丽田园", min_length=1, max_length=24)
    title: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=5, max_length=1200)
    caption: str = Field(default="", max_length=1200)
    aspect: Literal["square", "portrait", "landscape"] = "portrait"
    project_id: UUID | None = None
    video_cost_acknowledged: bool = False

    @field_validator("brand", "title", "prompt", "caption", mode="before")
    @classmethod
    def trim(cls, value: str) -> str:
        return value.strip()


PUBLIC_COLUMNS = (
    "id,kind,state,brand,title,prompt,caption,aspect,project_id,simulated,model,"
    "error_code,asset_mime,asset_bytes,created_at,updated_at"
)


def public_job(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: row[key] for key in PUBLIC_COLUMNS.split(",")},
        "can_reconcile": bool(row.get("provider_task_id") or row.get("provider_asset_url")),
    }


class MarketingService:
    def __init__(self, repo: Repository, settings: Settings, actor: Actor, store: str):
        self.repo, self.settings, self.actor, self.store = repo, settings, actor, store

    def grant(self) -> None:
        StaffBookingService(self.repo, self.settings, self.actor, self.store).grant(
            "knowledge_author"
        )

    def options(self) -> dict[str, Any]:
        self.grant()
        projects = self.repo.all(
            "SELECT k.id,k.title,k.content,k.simulated,d.entities FROM knowledge_version k "
            "JOIN knowledge_detail d ON d.version_id=k.id "
            "JOIN publication p ON p.version_id=k.id AND p.state='ready' "
            "WHERE k.tenant_id=%s AND k.store_id=%s AND k.status='published' "
            "AND k.valid_until>now() AND k.knowledge_key LIKE 'catalog-%%' "
            "AND (%s OR NOT k.simulated) ORDER BY k.title LIMIT 100",
            (self.actor.tenant_id, self.store, self.settings.allow_simulated_data),
        )
        return {
            "image_ready": bool(self.settings.marketing_image_api_key.get_secret_value()),
            "video_ready": self.settings.marketing_video_enabled
            and bool(self.settings.marketing_video_api_key.get_secret_value()),
            "image_model": IMAGE_MODEL,
            "video_model": VIDEO_MODEL,
            "daily_limit": self.settings.marketing_daily_limit,
            "projects": [
                {
                    "id": row["id"],
                    "title": next(
                        (e["name"] for e in row["entities"] if e.get("kind") == "Project"),
                        row["title"],
                    ),
                    "description": row["content"],
                    "simulated": row["simulated"],
                }
                for row in projects
            ],
        }

    def list(self, offset: int = 0) -> dict[str, Any]:
        self.grant()
        return {
            "items": self.repo.all(
                f"SELECT {PUBLIC_COLUMNS},"
                "(provider_task_id IS NOT NULL OR provider_asset_url IS NOT NULL) "
                "AS can_reconcile FROM marketing_job WHERE tenant_id=%s AND store_id=%s "
                "ORDER BY created_at DESC,id DESC LIMIT 20 OFFSET %s",
                (self.actor.tenant_id, self.store, offset),
            )
        }

    def get(self, job: str) -> dict[str, Any]:
        self.grant()
        row = self.repo.one(
            "SELECT * FROM marketing_job WHERE id=%s AND tenant_id=%s AND store_id=%s",
            (job, self.actor.tenant_id, self.store),
        )
        if not row:
            raise DomainError("marketing_not_found", 404)
        return row

    def create(self, data: MarketingInput, request_id: str) -> dict[str, Any]:
        self.grant()
        # Serialize quota/idempotency without upgrading the grant's shared store lock.
        self.repo.one(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("marketing:" + self.store,)
        )
        store = self.repo.one(
            "SELECT id,name,simulated FROM store WHERE tenant_id=%s AND id=%s",
            (self.actor.tenant_id, self.store),
        )
        assert store
        payload = data.model_dump(mode="json")
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        existing = self.repo.one(
            "SELECT * FROM marketing_job WHERE tenant_id=%s AND store_id=%s AND request_key=%s",
            (self.actor.tenant_id, self.store, data.request_key),
        )
        if existing:
            if existing["request_hash"] != fingerprint:
                raise DomainError("marketing_key_conflict", 409)
            return public_job(existing)
        if data.kind == "image" and not self.settings.marketing_image_api_key.get_secret_value():
            raise DomainError("marketing_image_unconfigured", 409)
        if data.kind == "video" and not (
            self.settings.marketing_video_enabled
            and self.settings.marketing_video_api_key.get_secret_value()
        ):
            raise DomainError("marketing_video_unconfigured", 409)
        if data.kind == "video" and not data.video_cost_acknowledged:
            raise DomainError("marketing_video_cost_required", 422)
        count = self.repo.one(
            "SELECT count(*) AS n FROM marketing_job WHERE tenant_id=%s AND store_id=%s "
            "AND created_at>=date_trunc('day',now())",
            (self.actor.tenant_id, self.store),
        )
        if count and count["n"] >= self.settings.marketing_daily_limit:
            raise DomainError("marketing_daily_limit", 429)
        if data.project_id and not any(
            str(p["id"]) == str(data.project_id) for p in self.options()["projects"]
        ):
            raise DomainError("project_unavailable", 409)
        job_id = str(uuid4())
        model = IMAGE_MODEL if data.kind == "image" else VIDEO_MODEL
        self.repo.execute(
            "INSERT INTO marketing_job(id,tenant_id,store_id,staff_id,request_key,request_hash,"
            "kind,brand,title,prompt,caption,aspect,project_id,simulated,model) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                job_id,
                self.actor.tenant_id,
                self.store,
                self.actor.id,
                data.request_key,
                fingerprint,
                data.kind,
                data.brand,
                data.title,
                data.prompt,
                data.caption,
                data.aspect,
                data.project_id,
                store["simulated"],
                model,
            ),
        )
        self.repo.audit(self.actor, "marketing.create", job_id, request_id)
        return public_job(self.get(job_id))

    def asset(self, job: str) -> tuple[Path, str]:
        row = self.get(job)
        if row["state"] != "succeeded" or not row["asset_name"]:
            raise DomainError("marketing_asset_unavailable", 409)
        root = Path(self.settings.marketing_media_root).resolve()
        path = (root / row["asset_name"]).resolve()
        if path.parent != root or not path.is_file():
            raise DomainError("marketing_asset_unavailable", 404)
        return path, row["asset_mime"]

    def cancel(self, job: str, request_id: str) -> dict[str, Any]:
        self.get(job)
        changed = self.repo.one(
            f"UPDATE marketing_job SET state='cancelled',updated_at=now() WHERE id=%s "
            f"AND state='queued' RETURNING {PUBLIC_COLUMNS}",
            (job,),
        )
        if not changed:
            raise DomainError("marketing_state_conflict", 409)
        self.repo.audit(self.actor, "marketing.cancel", job, request_id)
        return public_job(changed)

    def reconcile(self, job: str, request_id: str) -> dict[str, Any]:
        row = self.get(job)
        if row["state"] not in ("unknown", "failed") or not (
            row["provider_task_id"] or row["provider_asset_url"]
        ):
            raise DomainError("marketing_state_conflict", 409)
        changed = self.repo.one(
            "UPDATE marketing_job SET state='running',error_code=NULL,available_at=now(),"
            "lease_token=NULL,lease_until=NULL,attempts=0,updated_at=now() WHERE id=%s "
            "AND state IN ('unknown','failed') RETURNING *",
            (job,),
        )
        if not changed:
            raise DomainError("marketing_state_conflict", 409)
        self.repo.audit(self.actor, "marketing.reconcile", job, request_id)
        return public_job(changed)
