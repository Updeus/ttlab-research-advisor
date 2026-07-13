from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("ttlab.api")


class RequestTooLargeError(Exception):
    pass


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

    LIMITED_PATHS = {
        ("POST", "/api/ask"),
        ("POST", "/api/recommendations/extensions"),
    }

    def __init__(self, app: ASGIApp, requests_per_minute: int) -> None:
        self.app = app
        self.requests_per_minute = requests_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (scope.get("method", ""), scope.get("path", "")) not in self.LIMITED_PATHS:
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        client_host = str(client[0]) if client else "unknown"
        key = f"{client_host}:{scope.get('path')}"
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
                    or path in {"/api/ask", "/api/recommendations/extensions"}
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
