from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
import uuid
from collections import defaultdict, deque

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from sqlalchemy.exc import OperationalError

logger = logging.getLogger("ttlab.api")

PUBLIC_GENERATION_PATHS = {
    ("POST", "/api/ask"),
    ("POST", "/api/recommendations/ideas"),
    ("POST", "/api/recommendations/extensions"),
}


class RequestTooLargeError(Exception):
    pass


class FeatureGateMiddleware:
    """Fail public APIs closed when an administrator disables a feature."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from sqlmodel import Session

        from app.db import engine
        from app.features import feature_for_path
        from app.models.admin import FeatureSetting

        feature_key = feature_for_path(str(scope.get("path") or ""))
        if feature_key:
            try:
                with Session(engine) as session:
                    setting = session.get(FeatureSetting, feature_key)
            except OperationalError as exc:
                # Startup creates/seeds this table before production traffic.
                # Test clients and migration/bootstrap probes may intentionally
                # invoke ASGI without running lifespan; preserve legacy-enabled
                # behavior until initialization completes.
                if "no such table" not in str(exc).lower():
                    raise
                setting = None
            if setting is not None and not setting.enabled:
                response = JSONResponse(
                    {
                        "detail": {
                            "code": "feature_disabled",
                            "feature": feature_key,
                            "message": setting.disabled_message or "This feature is temporarily disabled.",
                        }
                    },
                    status_code=503,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


class RequestBodyLimitMiddleware:
    """Reject oversized request bodies, including chunked bodies."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                await self._reject(scope, receive, send, detail="Invalid Content-Length")
                return
        consumed = 0

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    raise RequestTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLargeError:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        detail: str = "Request body too large",
    ) -> None:
        response = JSONResponse({"detail": detail}, status_code=413)
        await response(scope, receive, send)


class PublicRateLimitMiddleware:
    """Small single-process limiter for anonymous generation endpoints."""

    LIMITED_PATHS = PUBLIC_GENERATION_PATHS

    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int,
        *,
        managed_postgres: bool = False,
        hash_salt: str | None = None,
    ) -> None:
        self.app = app
        self.requests_per_minute = requests_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self.managed_postgres = managed_postgres
        self.hash_salt = hash_salt or ""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (scope.get("method", ""), scope.get("path", "")) not in self.LIMITED_PATHS:
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        client_host = str(client[0]) if client else "unknown"
        key = f"{client_host}:{scope.get('path')}"
        if self.managed_postgres:
            digest = hashlib.sha256(f"{self.hash_salt}:{key}".encode("utf-8")).hexdigest()
            allowed = await asyncio.to_thread(self._admit_postgres, digest)
            if not allowed:
                response = JSONResponse(
                    {"detail": "Public generation rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
                await response(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return
        now = time.monotonic()
        async with self._lock:
            bucket = self._requests[key]
            while bucket and now - bucket[0] >= 60:
                bucket.popleft()
            if len(bucket) >= self.requests_per_minute:
                response = JSONResponse(
                    {"detail": "Public generation rate limit exceeded"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
                await response(scope, receive, send)
                return
            bucket.append(now)
        await self.app(scope, receive, send)

    def _admit_postgres(self, bucket_key: str) -> bool:
        from sqlalchemy import text

        from app.db import engine

        statement = text(
            "INSERT INTO public_rate_limit_bucket(bucket_key, window_start, request_count) "
            "VALUES (:key, date_trunc('minute', CURRENT_TIMESTAMP), 1) "
            "ON CONFLICT (bucket_key) DO UPDATE SET "
            "request_count = CASE WHEN public_rate_limit_bucket.window_start = date_trunc('minute', CURRENT_TIMESTAMP) "
            "THEN public_rate_limit_bucket.request_count + 1 ELSE 1 END, "
            "window_start = date_trunc('minute', CURRENT_TIMESTAMP) "
            "RETURNING request_count"
        )
        with engine.begin() as connection:
            count = int(connection.execute(statement, {"key": bucket_key}).scalar_one())
        return count <= self.requests_per_minute


class PublicGenerationConcurrencyMiddleware:
    """Bound concurrent public generation work and its in-process wait queue.

    This is a single-worker resource backstop, not a distributed admission
    controller. Production configuration therefore continues to reject more
    than one API worker unless an external limiter is implemented.
    """

    LIMITED_PATHS = PUBLIC_GENERATION_PATHS

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_concurrency: int,
        max_queue: int,
        queue_timeout_seconds: float,
    ) -> None:
        self.app = app
        self.max_concurrency = max_concurrency
        self.max_queue = max_queue
        self.queue_timeout_seconds = queue_timeout_seconds
        self._capacity = asyncio.BoundedSemaphore(max_concurrency)
        self._state_lock = asyncio.Lock()
        self._active = 0
        self._waiting = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (scope.get("method", ""), scope.get("path", "")) not in self.LIMITED_PATHS:
            await self.app(scope, receive, send)
            return

        async with self._state_lock:
            if self._active >= self.max_concurrency and self._waiting >= self.max_queue:
                await self._reject(scope, receive, send, "Public generation queue is full")
                return
            self._waiting += 1

        acquired = False
        admitted = False
        try:
            try:
                await asyncio.wait_for(
                    self._capacity.acquire(),
                    timeout=self.queue_timeout_seconds,
                )
                acquired = True
            except TimeoutError:
                async with self._state_lock:
                    self._waiting -= 1
                await self._reject(scope, receive, send, "Public generation queue wait timed out")
                return

            async with self._state_lock:
                self._waiting -= 1
                self._active += 1
                admitted = True
            await self.app(scope, receive, send)
        finally:
            if acquired and not admitted:
                async with self._state_lock:
                    self._waiting -= 1
                self._capacity.release()
            elif admitted:
                async with self._state_lock:
                    self._active -= 1
                self._capacity.release()

    async def _reject(self, scope: Scope, receive: Receive, send: Send, detail: str) -> None:
        response = JSONResponse(
            {"detail": detail},
            status_code=503,
            headers={"Retry-After": str(max(1, math.ceil(self.queue_timeout_seconds)))},
        )
        await response(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, security_mode: str, insecure_demo: bool) -> None:
        self.app = app
        self.security_mode = security_mode
        self.insecure_demo = insecure_demo

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started_at = time.perf_counter()
        response_status = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                headers["X-Request-ID"] = request_id
                headers["X-TTLAB-Security-Mode"] = self.security_mode
                if self.insecure_demo:
                    headers["X-TTLAB-Insecure-Demo"] = "true"
                if self.security_mode == "production":
                    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
                path = str(scope.get("path") or "")
                if (
                    path.startswith("/api/admin")
                    or "/history" in path
                    or path in {
                        "/api/ask",
                        "/api/recommendations/extensions",
                        "/api/recommendations/ideas",
                    }
                    or (path.startswith("/api/ask/") and not path.endswith("/diagnostics"))
                    or (
                        path.startswith("/api/recommendations/extensions/")
                        and not path.endswith("/diagnostics")
                    )
                ):
                    headers["Cache-Control"] = "no-store"
                if path.startswith("/api"):
                    headers["Content-Security-Policy"] = (
                        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
                    )
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            route = scope.get("route")
            route_template = getattr(route, "path", "unmatched")
            state = scope.get("state", {})
            logger.info(
                "request_completed method=%s route=%s status=%s duration_ms=%.2f request_id=%s actor_id=%s actor_role=%s",
                scope.get("method", "unknown"),
                route_template,
                response_status,
                (time.perf_counter() - started_at) * 1000,
                request_id,
                state.get("actor_id", "anonymous"),
                state.get("actor_role", "public"),
            )
