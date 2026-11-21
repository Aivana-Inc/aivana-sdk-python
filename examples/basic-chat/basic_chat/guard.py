"""The request guard: everything that must hold before a request reaches a route.

It is a plain ASGI middleware, not Starlette's BaseHTTPMiddleware, on purpose. BaseHTTPMiddleware wraps the
response body in its own stream, which sits between the browser and a streaming route. This one only looks at
the request on the way in and adds headers on the way out, so a hang-up reaches the route directly (that is what
lets Stop cancel the call to Aivana).

What it does, in order:
  1. Host check (every request): only the local address this server is listening on. A web page on another
     site cannot reach a local server by tricking the browser's DNS ("DNS rebinding"), because the Host
     header it sends would be that other site's name.
  2. For chat posts only: the Origin must be this app's own page, never another site; the body must be JSON.
  3. At most `max_active` chat requests at once (the Node starter's limit of two).
  4. The body is read here, with a size cap and a time limit, then handed to the route as if it had just arrived.
     Doing it here means a too-large or stalled body gets our own answer (413 or 408), not a generic one.
  5. Security headers on every response.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from .errors import envelope_bytes

log = logging.getLogger("basic_chat")

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]

CHAT_PATHS = ("/api/chat", "/api/chat/stream")
MAX_BODY_BYTES = 256 * 1024
BODY_TIMEOUT_S = 15.0
MAX_ACTIVE = 2

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
SECURITY_HEADERS = (
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy", CSP.encode()),
)


class RequestGuard:
    def __init__(self, app, *, max_active: int = MAX_ACTIVE, max_body: int = MAX_BODY_BYTES, body_timeout: float = BODY_TIMEOUT_S):
        self.app = app
        self.max_active, self.max_body, self.body_timeout = max_active, max_body, body_timeout
        self.active = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers.extend((name, value) for name, value in SECURITY_HEADERS if name not in present)
                message = {**message, "headers": headers}
            await send(message)

        async def refuse(status: int, code: str, text: str, *, close: bool = False) -> None:
            body = envelope_bytes(code, text)
            headers = [(b"content-type", b"application/json; charset=utf-8"), (b"content-length", str(len(body)).encode())]
            if close:
                headers.append((b"connection", b"close"))
            await send_with_headers({"type": "http.response.start", "status": status, "headers": headers})
            await send_with_headers({"type": "http.response.body", "body": body})

        async def run(app_receive: Receive) -> None:
            """Run the app. If it has a bug, answer with a fixed 500 and end the request normally.

            Letting the error escape would make uvicorn drop the connection mid-answer, which a browser can report
            as a network failure. The log says where it happened and what kind of error it was, never the
            exception's text: that text can contain what the person typed.
            """
            try:
                await self.app(scope, app_receive, send_with_headers)
            except Exception as error:  # noqa: BLE001
                log.error("unexpected %s while handling %s %s\n%s", type(error).__name__, scope["method"], scope["path"],
                          "".join(traceback.format_tb(error.__traceback__)))
                if not started:
                    await refuse(500, "internal_error", "Something went wrong in the local server. Check the terminal.", close=True)

        headers = {name.decode("latin-1").lower(): value.decode("latin-1") for name, value in scope["headers"]}
        server = scope.get("server")
        port = server[1] if server else None
        host = headers.get("host", "").lower()
        if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return await refuse(403, "forbidden", "Open this starter on its local address.")

        if scope["method"] != "POST" or scope["path"] not in CHAT_PATHS:
            return await run(receive)

        if headers.get("origin") != f"http://{host}" or headers.get("sec-fetch-site") == "cross-site":
            return await refuse(403, "forbidden", "Send messages from this app's local page.")
        if headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            return await refuse(415, "unsupported_media_type", "Send application/json.")
        if self.active >= self.max_active:
            return await refuse(429, "busy", "Two requests are already running. Wait before sending another.")

        self.active += 1
        try:
            body = await self._read_body(headers, receive, refuse)
            if body is None:
                return
            delivered = False

            async def replay() -> Message:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                # After the body, the real receive: it reports the browser hanging up, which a streaming
                # route listens for.
                return await receive()

            await run(replay)
        finally:
            self.active -= 1

    async def _read_body(self, headers: dict[str, str], receive: Receive, refuse) -> bytes | None:
        too_large = ("request_too_large", "This chat request is too large. Start a new chat.")
        declared = headers.get("content-length")
        if declared is not None:
            if not declared.isascii() or not declared.isdigit():
                await refuse(400, "invalid_request", "Send a valid JSON chat request.", close=True)
                return None
            if int(declared) > self.max_body:
                await refuse(413, *too_large, close=True)  # refused without reading a byte of it
                return None
        chunks: list[bytes] = []
        size = 0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.body_timeout
        while True:
            try:
                message = await asyncio.wait_for(receive(), max(deadline - loop.time(), 0))
            except TimeoutError:
                await refuse(408, "request_timeout", "The request took too long to arrive. Try again.", close=True)
                return None
            if message["type"] == "http.disconnect":
                return None
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.max_body:
                await refuse(413, *too_large, close=True)
                return None
            chunks.append(chunk)
            if not message.get("more_body", False):
                return b"".join(chunks)
