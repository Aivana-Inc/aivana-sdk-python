"""Test doubles for the CLI suites: a fake Intelligence API, and stand-ins for stdin
and a terminal. Used by conftest.py; not a test module itself."""
from __future__ import annotations

import io
import json
from typing import Any

import httpx


def sse(events: list) -> bytes:
    """Frames exactly as /v1/generate:stream writes them."""
    return "".join(f"event: {event}\ndata: {json.dumps(data)}\n\n"
                   for event, data in events).encode()


class FakeAPI:
    """Answers every request with `response`, recording what was sent.

    `response` has the conformance suite's shape (conformance/README.md):
    {"status", "events"} for a stream, {"status", "json"} for a JSON body,
    {"network_error": "connect" | "timeout"}, and "then": "disconnect".
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.response: dict[str, Any] = {"status": 200, "events": []}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        spec = self.response
        failure = spec.get("network_error")
        if failure == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        if failure:
            raise ValueError(f"unknown network_error {failure!r}")
        if "events" in spec:
            payload, content_type = sse(spec["events"]), "text/event-stream"
        else:
            payload, content_type = json.dumps(spec.get("json", {})).encode(), "application/json"

        def body():
            # A generator, never bytes: httpx pre-reads a body built from bytes, and
            # that is what hid the SDK's streaming error bug (see test_errors.py).
            yield payload
            if spec.get("then") == "disconnect":
                raise httpx.ReadError("connection reset", request=request)

        return httpx.Response(spec.get("status", 200),
                              headers={"content-type": content_type}, content=body())

    @property
    def sent(self) -> dict[str, Any]:
        """The JSON body of the last request."""
        return json.loads(self.requests[-1].content)


class Stdin(io.StringIO):
    """stdin: an interactive terminal (tty=True) or piped text (tty=False)."""

    def __init__(self, text: str = "", *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class Terminal(io.StringIO):
    """stderr as an interactive terminal, so the progress line is drawn."""

    def isatty(self) -> bool:
        return True
