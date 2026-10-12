from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol


def now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Actor:
    id: str
    tenant_id: str
    store_id: str | None
    kind: Literal["visitor", "staff"]
    session_id: str


class DomainError(Exception):
    def __init__(self, code: str, status: int = 403) -> None:
        self.code = code
        self.status = status


class Repository(Protocol):
    def one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None: ...
    def all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]: ...
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None: ...
    def audit(self, actor: Actor, action: str, resource: str, request_id: str) -> None: ...
