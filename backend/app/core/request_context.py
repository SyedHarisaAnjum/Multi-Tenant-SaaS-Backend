"""Per-request id: accepted from the client (if well-formed) or generated, echoed in the
X-Request-ID response header, included in error bodies and in every log line."""

import logging
import re
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
access_logger = logging.getLogger("app.access")


def get_request_id() -> str:
    return _request_id.get()


class RequestIdMiddleware:
    """Pure ASGI middleware (not BaseHTTPMiddleware) so it doesn't buffer responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        # Never trust arbitrary client input in logs: accept only short, safe ids.
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        # Not reset afterwards on purpose: the outermost 500 handler runs after this
        # middleware returns and still needs the id. Each request overwrites it.
        _request_id.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id

        status_code = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            # The client address as resolved by uvicorn from trusted proxy headers: the
            # same value per-IP rate limits use.
            client = scope.get("client")
            access_logger.info(
                "%s %s -> %s (%.1f ms) client=%s",
                scope["method"],
                scope["path"],
                status_code,
                (time.perf_counter() - started) * 1000,
                client[0] if client else "-",
            )
