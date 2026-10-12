from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.domain import Actor


class PostgresRepository:
    def __init__(self, connection: psycopg.Connection[dict[str, Any]]) -> None:
        self.connection = connection

    def one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        return self.connection.execute(query, params).fetchone()

    def all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return self.connection.execute(query, params).fetchall()

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        self.connection.execute(query, params)

    def audit(self, actor: Actor, action: str, resource: str, request_id: str) -> None:
        self.execute(
            "INSERT INTO audit(tenant_id,actor_id,action,resource,request_id,version_ref) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (
                actor.tenant_id,
                actor.id,
                action,
                resource,
                request_id,
                resource if action.startswith("knowledge.") else None,
            ),
        )


@contextmanager
def transaction(dsn: str) -> Iterator[PostgresRepository]:
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as connection:
        with connection.transaction():
            yield PostgresRepository(connection)
