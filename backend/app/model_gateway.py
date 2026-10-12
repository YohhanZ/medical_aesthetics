"""Single external model exit. Never log payloads, credentials or provider error bodies."""

import hashlib
import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.config import Settings


class GatewayError(Exception):
    def __init__(self, code: str, status: int | None = None) -> None:
        self.code = code
        self.status = status


class Embedder(Protocol):
    model: str

    def embed(self, text: str) -> list[float]: ...


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def redact_contacts(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[联系方式已移除]", text)
    text = re.sub(r"(?<!\d)(?:\+?86[- ]?)?1[3-9](?:[- ]?\d){9}(?!\d)", "[电话已移除]", text)
    text = re.sub(r"(?<!\d)\d[\d -]{6,}\d(?!\d)", "[号码已移除]", text)
    text = re.sub(
        r"(?:微信|WeChat|wechat|QQ|qq)\s*[:：号]?\s*[A-Za-z0-9_-]+", "[联系方式已移除]", text
    )
    return text


class CircuitBreaker:
    """Process-local initial breaker; multi-instance shared coordination is a later milestone."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.lock = threading.Lock()
        self.results: deque[tuple[float, bool]] = deque()
        self.open_until = 0.0
        self.probing = False
        self.probe_thread: int | None = None

    def enter(self) -> None:
        with self.lock:
            now = self.clock()
            if self.open_until:
                if now < self.open_until or self.probing:
                    raise GatewayError("circuit_open")
                self.probing = True
                self.probe_thread = threading.get_ident()

    def finish(self, success: bool) -> None:
        with self.lock:
            now = self.clock()
            if self.probing:
                if self.probe_thread != threading.get_ident():
                    return
                self.probing = False
                self.probe_thread = None
                self.open_until = 0.0 if success else now + 30
                self.results.clear()
                return
            if self.open_until:
                return
            self.results.append((now, success))
            while self.results and self.results[0][0] < now - 60:
                self.results.popleft()
            if len(self.results) >= 10:
                failures = sum(not result for _, result in self.results)
                if failures / len(self.results) >= 0.5:
                    self.open_until = now + 30


class QwenEmbeddingGateway:
    def __init__(
        self,
        settings: Settings,
        client: httpx.Client | None = None,
        breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.model: str = settings.embedding_model
        self.client = client or httpx.Client(
            timeout=12.0, follow_redirects=False, trust_env=settings.model_use_env_proxy
        )
        self.breaker = breaker or CircuitBreaker()
        self.sleep = sleep

    def close(self) -> None:
        self.client.close()

    def _prepare(self, text: str) -> str:
        # Knowledge import never grants export. A separate authorized snapshot adds exact hashes.
        if fingerprint(text) not in self.settings.model_export_hashes:
            raise GatewayError("export_not_authorized")
        if not self.settings.model_api_key.get_secret_value():
            raise GatewayError("model_not_configured")
        sanitized = redact_contacts(text)
        if not sanitized.strip() or len(sanitized) > 16000:
            raise GatewayError("invalid_model_input")
        return sanitized

    def _post(self, route: str, payload: dict[str, Any]) -> httpx.Response:
        self.breaker.enter()
        try:
            for attempt in range(2):
                deadline = getattr(self, "deadline", None)
                remaining = 12.0 if deadline is None else float(deadline) - time.monotonic()
                if remaining < 0.25:
                    raise GatewayError("turn_budget_exhausted")
                try:
                    response = self.client.post(
                        f"{self.settings.model_base_url}/{route}",
                        headers={
                            "Authorization": "Bearer "
                            + self.settings.model_api_key.get_secret_value()
                        },
                        json=payload,
                        timeout=min(12.0, remaining),
                    )
                except httpx.TransportError:
                    if attempt == 0:
                        self.sleep(0.25)
                        continue
                    raise GatewayError("model_transport_unavailable") from None
                if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    self.sleep(0.25)
                    continue
                if response.status_code != 200:
                    raise GatewayError("model_http_failure", response.status_code)
                return response
            raise GatewayError("model_unavailable")
        except GatewayError:
            self.breaker.finish(False)
            raise

    def embed(self, text: str) -> list[float]:
        sanitized = self._prepare(text)
        response = self._post(
            "embeddings", {"model": self.model, "input": [sanitized], "dimensions": 256}
        )
        try:
            values = response.json()["data"][0]["embedding"]
            if not isinstance(values, list) or len(values) != 256:
                raise ValueError
            if any(
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                for value in values
            ):
                raise ValueError
            vector = [float(value) for value in values]
            if not any(vector):
                raise ValueError
        except (ValueError, KeyError, IndexError, TypeError):
            self.breaker.finish(False)
            raise GatewayError("invalid_model_response") from None
        self.breaker.finish(True)
        return vector

    def probe_chat(self, text: str) -> dict[str, Any]:
        """Explicit synthetic connectivity check; not a customer conversation API."""
        sanitized = self._prepare(text)
        response = self._post(
            "chat/completions",
            {
                "model": self.settings.chat_model,
                "messages": [{"role": "user", "content": sanitized}],
                "stream": False,
                "enable_thinking": False,
                "max_tokens": 32,
            },
        )
        try:
            reply = response.json()["choices"][0]["message"]["content"]
            if not isinstance(reply, str) or not reply.strip():
                raise ValueError
        except (ValueError, KeyError, IndexError, TypeError):
            self.breaker.finish(False)
            raise GatewayError("invalid_model_response") from None
        self.breaker.finish(True)
        return {"status": "connected", "model": self.settings.chat_model}
