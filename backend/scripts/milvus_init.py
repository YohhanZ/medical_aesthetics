"""Offline privileged setup; application readers/workers receive separate limited accounts."""

import logging

from pymilvus import MilvusClient  # type: ignore[import-untyped]

from app.config import Settings
from app.vector_adapter import create_collection


def initialize(settings: Settings, *, include_test_collection: bool = True) -> None:
    logging.getLogger("pymilvus").setLevel(logging.CRITICAL)
    client = MilvusClient(
        uri=settings.milvus_uri, token=settings.milvus_admin_token.get_secret_value(), timeout=10
    )
    try:
        collections = [settings.milvus_collection]
        if include_test_collection:
            collections.append("ma_knowledge_test_256")
        for collection in collections:
            create_collection(client, collection)
        for token, role, privileges in (
            (
                settings.milvus_read_token,
                "ma_knowledge_reader",
                ["DescribeCollection", "Query", "Search", "GetStatistics"],
            ),
            (
                settings.milvus_write_token,
                "ma_knowledge_worker",
                ["DescribeCollection", "Query", "Upsert", "Delete", "GetStatistics"],
            ),
        ):
            username, password = token.get_secret_value().split(":", 1)
            if username not in client.list_users(timeout=5):
                client.create_user(user_name=username, password=password, timeout=5)
            if role not in client.list_roles(timeout=5):
                client.create_role(role_name=role, timeout=5)
            for collection in collections:
                for privilege in privileges:
                    client.grant_privilege_v2(
                        role_name=role,
                        privilege=privilege,
                        collection_name=collection,
                        db_name="default",
                        timeout=5,
                    )
            client.grant_role(user_name=username, role_name=role, timeout=5)
        print(
            "Milvus collections initialized: 256 dimensions, COSINE/HNSW; separate read/write roles"
        )
    finally:
        client.close()


if __name__ == "__main__":
    try:
        initialize(Settings())
    except Exception as error:
        raise SystemExit(
            f"Milvus initialization failed: {type(error).__name__}; provider details suppressed"
        ) from None
