"""Report counts scoped to this database's version IDs; no credentials or content."""

import json

from pymilvus import MilvusClient

from app.config import Settings
from app.db import transaction
from app.graph_adapter import Neo4jKnowledgeGraph

settings = Settings()
with transaction(settings.database_url) as repo:
    ids = [str(row["id"]) for row in repo.all("SELECT id FROM knowledge_version")]
    result = {
        "knowledge": repo.all(
            "SELECT status,count(*) AS count FROM knowledge_version GROUP BY status ORDER BY status"
        ),
        "publication": repo.all(
            "SELECT state,graph_ready,vector_ready,count(*) AS count "
            "FROM publication GROUP BY state,graph_ready,vector_ready"
        ),
        "outbox": repo.all(
            "SELECT last_error,count(*) AS count FROM outbox "
            "WHERE processed_at IS NULL GROUP BY last_error"
        ),
        "vector_receipts": repo.all(
            "SELECT state,collection_name,count(*) AS count FROM vector_projection "
            "GROUP BY state,collection_name"
        ),
    }
graph = Neo4jKnowledgeGraph(settings)
try:
    rows, _, _ = graph.driver.execute_query(
        "MATCH (v:KnowledgeVersion) WHERE v.version_id IN $ids RETURN count(v) AS versions",
        ids=ids,
        database_=graph.database,
    )
    result["graph"] = [dict(row) for row in rows]
finally:
    graph.close()
vectors = MilvusClient(
    uri=settings.milvus_uri,
    token=settings.milvus_read_token.get_secret_value(),
    timeout=settings.milvus_timeout,
)
try:
    count = 0
    for start in range(0, len(ids), 200):
        rows = vectors.query(
            settings.milvus_collection,
            filter=f"id in {json.dumps(ids[start : start + 200])}",
            output_fields=["count(*)"],
            consistency_level="Strong",
        )
        count += rows[0]["count(*)"]
    result["milvus"] = [{"collection": settings.milvus_collection, "owned_vectors": count}]
finally:
    vectors.close()
print(json.dumps(result))
