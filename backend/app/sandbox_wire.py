"""Bounded JSON-only IPC. No pickle, dynamic imports, executable payloads or error bodies."""

import json
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MAX_FRAME = 2 * 1024 * 1024
MAX_BYTES = 24 * 1024 * 1024
MAX_CALLS = 128


class SandboxJob(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(ge=1, le=1)
    run_id: str
    message_id: str
    thread_id: str
    simulated: bool
    demo_medical: bool
    timeout_seconds: float = Field(ge=10, le=60)


def normalize(value: Any, depth: int = 0) -> Any:
    if depth > 32:
        raise ValueError("ipc_depth")
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, date | datetime | UUID):
        return str(value)
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("ipc_keys")
        return {key: normalize(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [normalize(item, depth + 1) for item in value]
    raise ValueError("ipc_type")


def encode(value: Any) -> bytes:
    result = json.dumps(normalize(value), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(result) > MAX_FRAME:
        raise ValueError("ipc_size")
    return result + b"\n"


def decode(value: bytes) -> dict[str, Any]:
    if len(value) > MAX_FRAME + 1 or not value.endswith(b"\n"):
        raise ValueError("ipc_frame")
    result = json.loads(
        value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("ipc_nan"))
    )
    if not isinstance(result, dict):
        raise ValueError("ipc_object")
    normalize(result)
    return result
