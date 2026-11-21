"""Test helpers: real servers on real local sockets.

Nothing here is mocked at the HTTP level. The app runs under uvicorn, a stand-in for the Aivana API runs under
uvicorn too, and the real SDK talks to it. That is what lets the tests prove the things that only exist on a
real connection: that a browser hanging up reaches the API call, and that a stalled request is given up on.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from typing import Any

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

KEY = "synthetic_test_key_never_for_browser"


class _Server(uvicorn.Server):
    def install_signal_handlers(self) -> None:  # uvicorn may not touch signals outside the main thread
        pass


@contextmanager
def serve(app):
    """Run an ASGI app on a free local port for the duration of the block. Yields its base URL."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", access_log=False, timeout_graceful_shutdown=1)
    server = _Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(10)


def answer(**extra: Any) -> JSONResponse:
    """A normal non-streaming answer from the API."""
    body = {"id": "gen_1", "answer": "Synthetic answer", "intent": {"name": "analysis", "confidence": 0.9}, **extra}
    return JSONResponse(body)


def sse(*events: tuple, gap: float = 0.0, fail_after: int | None = None, upstream: Upstream | None = None) -> StreamingResponse:
    """A streamed answer. Each event is (name, data) or (delay_seconds, name, data).

    `upstream.closed` is set if the client leaves before the stream ends (the API seeing its caller hang up).
    `fail_after=N` breaks the connection after N events, the way a dropped network does.
    """

    async def body():
        finished = False
        try:
            for index, event in enumerate(events):
                if fail_after is not None and index >= fail_after:
                    raise ConnectionError("simulated drop")
                delay, name, data = event if len(event) == 3 else (gap, *event)
                if delay:
                    await asyncio.sleep(delay)
                yield f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()
            finished = True
        finally:
            if not finished and upstream is not None:
                upstream.closed.set()

    return StreamingResponse(body(), media_type="text/event-stream")


Respond = Callable[[dict, Request, int], Awaitable[Response | None]]


class Upstream:
    """A stand-in for the Aivana API: records every request and answers as the test says."""

    def __init__(self, respond: Respond):
        self.respond = respond
        self.seen: list[dict] = []
        self.closed = threading.Event()  # the caller hung up before the answer was complete
        self.release = threading.Event()  # lets a test hold requests open, then let them finish
        self.url = ""

        async def handle(request: Request) -> Response:
            entry = {"body": await request.json(), "headers": dict(request.headers), "path": request.url.path}
            self.seen.append(entry)
            response = await respond(entry, request, len(self.seen))
            if response is None:  # "never answer": hold the request until the caller gives up
                await self.wait_for_hangup(request)
                return Response(status_code=499)
            return response

        self.app = Starlette(routes=[Route("/v1/generate", handle, methods=["POST"]), Route("/v1/generate:stream", handle, methods=["POST"])])

    async def wait_for_hangup(self, request: Request) -> None:
        while not await request.is_disconnected():
            await asyncio.sleep(0.01)
        self.closed.set()

    async def wait_for_release(self) -> None:
        while not self.release.is_set():
            await asyncio.sleep(0.01)


def raw(port_url: str, data: bytes, wait: float = 1.5) -> tuple[bytes, str]:
    """Send bytes on a plain TCP socket and report what came back and how the connection ended."""
    host, port = port_url.removeprefix("http://").split(":")
    sock = socket.create_connection((host, int(port)), timeout=wait + 2)
    out = b""
    try:
        try:
            sock.sendall(data)
        except (ConnectionResetError, BrokenPipeError):
            return out, "cut off by server while sending"
        sock.settimeout(wait)
        try:
            while True:
                part = sock.recv(65536)
                if not part:
                    return out, "closed by server"
                out += part
        except TimeoutError:
            return out, "still open"
        except ConnectionResetError:
            return out, "reset by server"
    finally:
        sock.close()


def status_of(data: bytes) -> int:
    return int(data.split(b" ", 2)[1]) if data.startswith(b"HTTP/1.1 ") else 0


def body_of(data: bytes) -> bytes:
    return data.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in data else b""


class Page:
    """A tiny browser stand-in: posts like the page does (same Origin) to one app."""

    def __init__(self, origin: str):
        self.origin = origin
        self.http = httpx.Client(base_url=origin, timeout=10)

    def post(self, body: Any, *, path: str = "/api/chat", headers: dict | None = None) -> httpx.Response:
        merged = {"Origin": self.origin, "Content-Type": "application/json", **(headers or {})}
        content = body if isinstance(body, (str, bytes)) else json.dumps(body)
        return self.http.post(path, content=content, headers=merged)

    def close(self) -> None:
        self.http.close()
