"""HTTP middleware for request correlation."""

import uuid

from redis.exceptions import RedisError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.cache import Cache
from app.core.config import Settings, get_settings
from app.core.security import access_token_subject
from app.logging_config import request_id_context


class RequestIdMiddleware:
    """Propagate a request ID through logs and the response header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_request_id = headers.get(b"x-request-id")
        request_id = (
            raw_request_id.decode("latin-1").strip() if raw_request_id else ""
        ) or str(uuid.uuid4())
        token = request_id_context.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_context.reset(token)


class RateLimitMiddleware:
    """Apply fixed-window IP and authenticated-user request limits."""

    def __init__(
        self,
        app: ASGIApp,
        cache: Cache,
        settings: Settings | None = None,
    ) -> None:
        self.app = app
        self.cache = cache
        self.settings = settings or get_settings()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        limits = [
            (f"rate:ip:{client_ip}", self.settings.rate_limit_ip_per_minute),
        ]
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            user_id = access_token_subject(token)
            if user_id is not None:
                limits.append(
                    (f"rate:user:{user_id}", self.settings.rate_limit_user_per_minute)
                )

        try:
            exceeded = any(
                self.cache.increment(key, 60) > limit for key, limit in limits
            )
        except RedisError:
            response = JSONResponse(
                status_code=503,
                content={"detail": "Rate-limit service is unavailable."},
            )
            await response(scope, receive, send)
            return

        if exceeded:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded."},
                headers={"Retry-After": "60"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
