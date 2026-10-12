from typing import Any, Protocol

from neo4j import GraphDatabase, ManagedTransaction, Query

from app.config import Settings


class KnowledgeGraph(Protocol):
    def project(self, version: dict[str, Any]) -> None: ...
    def remove(self, tenant_id: str, store_id: str, version_id: str) -> None: ...
    def expand(
        self, tenant_id: str, store_id: str, version_ids: list[str], topics: list[str]
    ) -> list[str]: ...


class Neo4jKnowledgeGraph:
    def __init__(self, settings: Settings, read_timeout: float | None = None) -> None:
        if not settings.neo4j_password.get_secret_value():
            raise RuntimeError("Configure the isolated knowledge graph credential")
        self.database = settings.neo4j_database
        self.read_timeout = read_timeout
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
            connection_timeout=read_timeout or 5,
            max_transaction_retry_time=0 if read_timeout else 10,
        )

    def close(self) -> None:
        self.driver.close()

    def setup(self) -> None:
        for label in ("KnowledgeVersion", "KnowledgeEntity"):
            # Labels are fixed application constants, never model/user-generated Cypher.
            self.driver.execute_query(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) "
                "REQUIRE (n.tenant_id,n.store_id,n.version_id,n.key) IS UNIQUE",
                database_=self.database,
            )

    def project(self, version: dict[str, Any]) -> None:
        params = {
            "tenant": str(version["tenant_id"]),
            "store": str(version["store_id"]),
            "id": str(version["id"]),
            "key": version["knowledge_key"],
            "version": version["version"],
            "hash": version["content_hash"],
            "simulated": version["simulated"],
            "audience": version["audience"],
            "valid_until": version["valid_until"].isoformat(),
            "topics": version["topics"],
            "entities": version["entities"],
            "relations": version["relations"],
        }

        def write(tx: ManagedTransaction) -> None:
            tx.run(
                "MERGE (v:KnowledgeVersion {tenant_id:$tenant,store_id:$store,"
                "version_id:$id,key:$key}) "
                "SET v.version=$version,v.content_hash=$hash,v.simulated=$simulated,"
                "v.audience=$audience,v.valid_until=$valid_until,v.topics=$topics "
                "WITH v UNWIND $entities AS entity "
                "MERGE (e:KnowledgeEntity {tenant_id:$tenant,store_id:$store,"
                "version_id:$id,key:entity.key}) "
                "SET e.kind=entity.kind,e.name=entity.name,e.simulated=$simulated "
                "MERGE (v)-[:SUPPORTS]->(e)",
                **params,
            ).consume()
            tx.run(
                "UNWIND $relations AS relation "
                "MATCH (a:KnowledgeEntity {tenant_id:$tenant,store_id:$store,"
                "version_id:$id,key:relation.source}) "
                "MATCH (b:KnowledgeEntity {tenant_id:$tenant,store_id:$store,"
                "version_id:$id,key:relation.target}) "
                "MERGE (a)-[r:ASSERTION {kind:relation.kind}]->(b) "
                "SET r.knowledge_version_id=$id,r.tenant_id=$tenant,r.store_id=$store,"
                "r.simulated=$simulated,r.valid_until=$valid_until",
                **params,
            ).consume()

        with self.driver.session(database=self.database) as session:
            session.execute_write(write)

    def remove(self, tenant_id: str, store_id: str, version_id: str) -> None:
        self.driver.execute_query(
            "MATCH (n) WHERE (n:KnowledgeVersion OR n:KnowledgeEntity) "
            "AND n.tenant_id=$tenant AND n.store_id=$store AND n.version_id=$id DETACH DELETE n",
            tenant=tenant_id,
            store=store_id,
            id=version_id,
            database_=self.database,
        )

    def expand(
        self, tenant_id: str, store_id: str, version_ids: list[str], topics: list[str]
    ) -> list[str]:
        records, _, _ = self.driver.execute_query(
            Query(
                "MATCH (v:KnowledgeVersion) WHERE v.tenant_id=$tenant AND v.store_id=$store "
                "AND v.version_id IN $ids AND v.audience='public' "
                "AND any(topic IN v.topics WHERE topic IN $topics) "
                "RETURN v.version_id AS id ORDER BY id LIMIT 20",
                timeout=self.read_timeout,
            ),
            tenant=tenant_id,
            store=store_id,
            ids=version_ids,
            topics=topics,
            database_=self.database,
            routing_="r",
        )
        return [str(record["id"]) for record in records]
