"""Real authenticated local Milvus; test collection only, random IDs, no collection resets."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.config import Settings
from app.domain import now
from app.vector_adapter import MilvusVectorStore, VectorDocument, VectorError, scope_filter


@pytest.fixture
def vectors() -> Iterator[
    tuple[Settings, MilvusVectorStore, MilvusVectorStore, list[VectorDocument]]
]:
    settings = Settings(milvus_collection="ma_knowledge_test_256")
    if settings.milvus_uri != "http://127.0.0.1:59531":
        raise RuntimeError("Real Milvus tests require the isolated local port")
    writer = MilvusVectorStore(settings, write=True)
    reader = MilvusVectorStore(settings)
    created: list[VectorDocument] = []
    try:
        yield settings, writer, reader, created
    finally:
        for document in created:
            writer.remove(document.tenant_id, document.store_id, document.id)
        reader.close()
        writer.close()


def document(**changes: Any) -> VectorDocument:
    return VectorDocument(
        **{
            "id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "store_id": str(uuid4()),
            "knowledge_key": "test-only-synthetic",
            "version": 1,
            "content_hash": "a" * 64,
            "model": "test-only-embedding",
            "audience": "public",
            "simulated": True,
            "valid_until": now() + timedelta(days=1),
            **changes,
        }
    )


def test_actual_milvus_upsert_reconcile_search_isolation_and_delete(vectors: Any) -> None:
    _, writer, reader, created = vectors
    a = document()
    b = document(store_id=a.store_id)
    c = document(tenant_id=a.tenant_id)
    internal = document(tenant_id=a.tenant_id, store_id=a.store_id, audience="internal")
    expired = document(
        tenant_id=a.tenant_id, store_id=a.store_id, valid_until=now() - timedelta(days=1)
    )
    vector = [1.0] + [0.0] * 255
    for item in (a, b, c, internal, expired):
        created.append(item)
        writer.upsert(item, vector)
        assert writer.inspect(item) == "match"
    writer.upsert(a, vector)
    ids = [item.id for item in created]
    rows = reader.search(a.tenant_id, a.store_id, ids, vector, a.model, True)
    assert [row["version_id"] for row in rows] == [a.id]
    assert reader.search(a.tenant_id, a.store_id, ids, vector, a.model, False) == []
    assert reader.search(a.tenant_id, a.store_id, ids, vector, "wrong-model", True) == []
    assert (
        writer.inspect(document(id=a.id, tenant_id=a.tenant_id, store_id=a.store_id)) == "conflict"
    )
    writer.remove(a.tenant_id, a.store_id, a.id)
    assert writer.inspect(a) == "missing"


def test_actual_milvus_reader_cannot_write(vectors: Any) -> None:
    _, _, reader, created = vectors
    item = document()
    created.append(item)
    with pytest.raises(VectorError) as failure:
        reader.upsert(item, [1.0] + [0.0] * 255)
    assert failure.value.code == "vector_write_unknown"
    assert reader.inspect(item) == "missing"


def test_filters_and_vectors_reject_untrusted_values(vectors: Any) -> None:
    _, writer, _, _ = vectors
    with pytest.raises(ValueError):
        scope_filter('" or true', str(uuid4()))
    with pytest.raises(VectorError) as failure:
        writer.upsert(document(), [float("inf")] * 256)
    assert failure.value.code == "invalid_vector"
