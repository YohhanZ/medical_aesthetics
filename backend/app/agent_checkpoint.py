"""Scoped JSON-only LangGraph checkpointer; every read/write revalidates the run lease."""

from collections.abc import Iterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from psycopg.types.json import Jsonb

from app.agent_repository import PostgresAgentStore
from app.db import transaction
from app.domain import DomainError


class ScopedCheckpointSaver(BaseCheckpointSaver[int]):
    def __init__(self, store: PostgresAgentStore, run_id: str, lease: str) -> None:
        super().__init__()
        self.store, self.run_id, self.lease = store, run_id, lease

    def _config(self, checkpoint_id: str) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": self.run_id,
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint_id,
            }
        }

    def _validate(self, config: RunnableConfig) -> None:
        values = config.get("configurable", {})
        if values.get("thread_id") != self.run_id or values.get("checkpoint_ns", ""):
            raise DomainError("checkpoint_scope_denied")

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        self._validate(config)
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        with transaction(self.store.settings.database_url) as repo:
            self.store.owns(repo, self.run_id, self.lease)
            row = repo.one(
                "SELECT * FROM agent_checkpoint WHERE run_id=%s "
                "AND (%s::text IS NULL OR checkpoint_id=%s) ORDER BY checkpoint_id DESC LIMIT 1",
                (self.run_id, checkpoint_id, checkpoint_id),
            )
            if not row:
                return None
            writes = repo.all(
                "SELECT task_id,channel,value FROM agent_checkpoint_write "
                "WHERE run_id=%s AND checkpoint_id=%s ORDER BY task_id,write_idx",
                (self.run_id, row["checkpoint_id"]),
            )
            return CheckpointTuple(
                self._config(row["checkpoint_id"]),
                row["checkpoint"],
                row["metadata"],
                self._config(row["parent_id"]) if row["parent_id"] else None,
                [(item["task_id"], item["channel"], item["value"]) for item in writes],
            )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        self._validate(config)
        with transaction(self.store.settings.database_url) as repo:
            self.store.owns(repo, self.run_id, self.lease)
            repo.execute(
                "INSERT INTO agent_checkpoint(run_id,checkpoint_id,parent_id,checkpoint,metadata) "
                "VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    self.run_id,
                    checkpoint["id"],
                    config.get("configurable", {}).get("checkpoint_id"),
                    Jsonb(checkpoint),
                    Jsonb(metadata),
                ),
            )
        return self._config(checkpoint["id"])

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self._validate(config)
        with transaction(self.store.settings.database_url) as repo:
            self.store.owns(repo, self.run_id, self.lease)
            for index, (channel, value) in enumerate(writes):
                # Never serialize provider exceptions, arbitrary objects or raw prompt callbacks.
                if channel == "__error__":
                    value = {"code": "node_failed"}
                repo.execute(
                    "INSERT INTO agent_checkpoint_write(run_id,checkpoint_id,"
                    "task_id,write_idx,channel,value) "
                    "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        self.run_id,
                        config["configurable"]["checkpoint_id"],
                        task_id,
                        WRITES_IDX_MAP.get(channel, index),
                        channel,
                        Jsonb(value),
                    ),
                )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        # Application recovery uses the latest scoped checkpoint; no global time-travel API.
        if config is None or filter or before:
            raise DomainError("checkpoint_scope_denied")
        value = self.get_tuple(config)
        if value and limit != 0:
            yield value
