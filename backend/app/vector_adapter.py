"""Milvus projection and scoped vector search; no raw knowledge/customer text is stored here."""

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from app.config import Settings


class VectorError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


@dataclass(frozen=True)
class VectorDocument:
    id: str
    tenant_id: str
    store_id: str
    knowledge_key: str
    version: int
    content_hash: str
    model: str
    audience: Literal["public", "internal"]
    simulated: bool
    valid_until: datetime

    def row(self, embedding: list[float]) -> dict[str, Any]:
        validate_vector(embedding)
        for value in (self.id, self.tenant_id, self.store_id):
            UUID(value)
        return {
            **self.__dict__,
            "valid_until": int(self.valid_until.timestamp()),
            "embedding": embedding,
        }


class VectorStore(Protocol):
    collection: str

    def inspect(self, document: VectorDocument) -> Literal["missing", "match", "conflict"]: ...
    def upsert(self, document: VectorDocument, embedding: list[float]) -> None: ...
    def remove(self, tenant_id: str, store_id: str, version_id: str) -> None: ...
    def search(
        self,
        tenant_id: str,
        store_id: str,
        version_ids: list[str],
        embedding: list[float],
        model: str,
        allow_simulated: bool,
    ) -> list[dict[str, Any]]: ...


def validate_vector(values: list[float]) -> None:
    if (
        len(values) != 256
        or any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            for value in values
        )
        or not any(values)
    ):
        raise VectorError("invalid_vector")


def scope_filter(tenant_id: str, store_id: str, version_id: str | None = None) -> str:
    # UUID validation plus JSON string encoding; no user-supplied filter expressions.
    parts = [
        f"tenant_id == {json.dumps(str(UUID(tenant_id)))}",
        f"store_id == {json.dumps(str(UUID(store_id)))}",
    ]
    if version_id:
        parts.append(f"id == {json.dumps(str(UUID(version_id)))}")
    return " and ".join(parts)


def create_collection(client: Any, name: str) -> None:
    from pymilvus import DataType, MilvusClient  # type: ignore[import-untyped]

    if not client.has_collection(name, timeout=5):
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        for field, length in (
            ("id", 36),
            ("tenant_id", 36),
            ("store_id", 36),
            ("knowledge_key", 80),
            ("content_hash", 64),
            ("model", 80),
            ("audience", 8),
        ):
            schema.add_field(
                field_name=field,
                datatype=DataType.VARCHAR,
                max_length=length,
                is_primary=field == "id",
            )
        schema.add_field(field_name="version", datatype=DataType.INT64)
        schema.add_field(field_name="valid_until", datatype=DataType.INT64)
        schema.add_field(field_name="simulated", datatype=DataType.BOOL)
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=256)
        indexes = MilvusClient.prepare_index_params()
        indexes.add_index(
            field_name="embedding",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        client.create_collection(
            collection_name=name,
            schema=schema,
            index_params=indexes,
            consistency_level="Strong",
            timeout=30,
        )
    description = client.describe_collection(name, timeout=5)
    fields = {field["name"]: field for field in description["fields"]}
    if fields.get("embedding", {}).get("params", {}).get("dim") != 256:
        raise VectorError("vector_schema_mismatch")
    client.load_collection(name, timeout=30)


class MilvusVectorStore:
    def __init__(self, settings: Settings, *, write: bool = False) -> None:
        token = settings.milvus_write_token if write else settings.milvus_read_token
        if not token.get_secret_value():
            raise VectorError("milvus_not_configured")
        self.collection = settings.milvus_collection
        self.timeout = settings.milvus_timeout
        self.uri = settings.milvus_uri
        self.token = token
        self.client: Any = None

    def _api(self) -> Any:
        if self.client is None:
            from pymilvus import MilvusClient

            logging.getLogger("pymilvus").setLevel(logging.CRITICAL)
            try:
                self.client = MilvusClient(
                    uri=self.uri, token=self.token.get_secret_value(), timeout=self.timeout
                )
            except Exception:
                raise VectorError("vector_connection_unavailable") from None
        return self.client

    def close(self) -> None:
        if self.client is not None:
            self.client.close()

    def inspect(self, document: VectorDocument) -> Literal["missing", "match", "conflict"]:
        try:
            rows = self._api().query(
                self.collection,
                filter=scope_filter(document.tenant_id, document.store_id, document.id),
                output_fields=[
                    "id",
                    "content_hash",
                    "model",
                    "version",
                    "audience",
                    "simulated",
                    "valid_until",
                ],
                consistency_level="Strong",
                timeout=self.timeout,
            )
        except Exception:
            raise VectorError("vector_query_unavailable") from None
        if not rows:
            return "missing"
        row = rows[0]
        matches = all(
            row[key] == value
            for key, value in (
                ("content_hash", document.content_hash),
                ("model", document.model),
                ("version", document.version),
                ("audience", document.audience),
                ("simulated", document.simulated),
                ("valid_until", int(document.valid_until.timestamp())),
            )
        )
        return "match" if matches else "conflict"

    def upsert(self, document: VectorDocument, embedding: list[float]) -> None:
        row = document.row(embedding)
        try:
            self._api().upsert(self.collection, data=[row], timeout=self.timeout)
        except Exception:
            # The server may have committed despite a transport timeout; caller must reconcile.
            raise VectorError("vector_write_unknown") from None

    def remove(self, tenant_id: str, store_id: str, version_id: str) -> None:
        expression = scope_filter(tenant_id, store_id, version_id)
        try:
            self._api().delete(self.collection, filter=expression, timeout=self.timeout)
            if self._api().query(
                self.collection,
                filter=expression,
                output_fields=["id"],
                consistency_level="Strong",
                timeout=self.timeout,
            ):
                raise VectorError("vector_delete_unknown")
        except Exception:
            raise VectorError("vector_delete_unknown") from None

    def search(
        self,
        tenant_id: str,
        store_id: str,
        version_ids: list[str],
        embedding: list[float],
        model: str,
        allow_simulated: bool,
    ) -> list[dict[str, Any]]:
        validate_vector(embedding)
        if not version_ids:
            return []
        ids = [str(UUID(value)) for value in version_ids]
        base = scope_filter(tenant_id, store_id)
        # Bound the allowed-ID filter without silently dropping evidence from large tenants.
        hits: dict[str, dict[str, Any]] = {}
        try:
            for start in range(0, len(ids), 200):
                expression = (
                    base
                    + f" and id in {json.dumps(ids[start : start + 200])}"
                    + f' and model == {json.dumps(model)} and audience == "public"'
                    + " and valid_until > "
                    + str(int(datetime.now().timestamp()))
                )
                if not allow_simulated:
                    expression += " and simulated == false"
                batches = self._api().search(
                    self.collection,
                    data=[embedding],
                    filter=expression,
                    limit=20,
                    output_fields=["id", "content_hash", "model", "version"],
                    search_params={"metric_type": "COSINE", "params": {"ef": 64}},
                    consistency_level="Strong",
                    timeout=self.timeout,
                )
                for hit in batches[0]:
                    entity = hit["entity"]
                    hits[str(entity["id"])] = {
                        "version_id": str(entity["id"]),
                        "content_hash": entity["content_hash"],
                        "model": entity["model"],
                        "version": entity["version"],
                        "score": float(hit["distance"]),
                    }
        except Exception:
            raise VectorError("vector_search_unavailable") from None
        return sorted(hits.values(), key=lambda row: -float(row["score"]))[:20]
