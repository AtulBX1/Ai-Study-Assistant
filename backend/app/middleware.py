"""HTTP middleware for request correlation."""

import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
