"""Stop reaches Aivana.

When the person presses Stop (or closes the tab) the browser drops its connection. The app must then drop its
call to Aivana at once, so nothing keeps being generated, and billed, for an answer nobody will read.

This is the property that decides the framework choice: an async server can cancel a call that is still waiting
for its first word, and a synchronous one cannot. It also depends on how Starlette and uvicorn cooperate, so this
file is the guard on upgrading them: if a new version breaks it, these tests fail and requirements.txt must not move.
"""

from __future__ import annotations

import json
import socket
import time

import pytest

from .support import sse

LIMIT_S = 1.0  # how long the call to Aivana may stay open after the browser leaves


def post_raw(origin: str, path: str, message: str = "Hi") -> socket.socket:
    host, port = origin.removeprefix("http://").split(":")
    body = json.dumps({"message": message}).encode()
    sock = socket.create_connection((host, int(port)), timeout=10)
    sock.sendall(b"POST %s HTTP/1.1\r\nHost: %s:%s\r\nOrigin: %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
                 % (path.encode(), host.encode(), port.encode(), origin.encode(), len(body), body))
    return sock


def wait_until(condition, seconds: float = 5.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.005)
    return False


def read_until(sock: socket.socket, marker: bytes, seconds: float = 5.0) -> bytes:
    sock.settimeout(seconds)
    data = b""
    while marker not in data:
        part = sock.recv(4096)
        if not part:
            break
        data += part
    return data


def make(fixture, script):
    holder: dict = {}

    async def respond(entry, request, count):
        return sse(*script, upstream=holder["upstream"])

    app = fixture(respond)
    holder["upstream"] = app.upstream
    return app


def test_stop_while_thinking_reaches_the_api_at_once(fixture):
    """Before a single word has arrived: the case a synchronous server cannot handle."""
    app = make(fixture, [(5, "delta", {"text": "far too late"}), ("done", {"intent": {"name": "x"}})])
    sock = post_raw(app.origin, "/api/chat/stream")
    assert wait_until(lambda: app.seen), "the request reached the API"
    time.sleep(0.3)  # still "Thinking": nothing has been written to the browser
    left = time.monotonic()
    sock.close()
    assert app.upstream.closed.wait(LIMIT_S), "the call to Aivana was still open after Stop"
    assert time.monotonic() - left < LIMIT_S


def test_stop_in_the_middle_of_an_answer_reaches_the_api_at_once(fixture):
    app = make(fixture, [(0, "delta", {"text": "first "})] + [(0.2, "delta", {"text": "more "})] * 40 + [("done", {"intent": {"name": "x"}})])
    sock = post_raw(app.origin, "/api/chat/stream")
    assert b'"delta"' in read_until(sock, b'"delta"'), "text started arriving"
    left = time.monotonic()
    sock.close()
    assert app.upstream.closed.wait(LIMIT_S), "the call to Aivana was still open after Stop"
    assert time.monotonic() - left < LIMIT_S


def test_closing_the_tab_before_the_page_finished_sending_behaves_the_same(fixture):
    app = make(fixture, [(5, "delta", {"text": "x"}), ("done", {"intent": {"name": "x"}})])
    sock = post_raw(app.origin, "/api/chat/stream")
    assert wait_until(lambda: app.seen)
    sock.shutdown(socket.SHUT_RDWR)  # a reset or a half-close, as some browsers do on tab close
    sock.close()
    assert app.upstream.closed.wait(LIMIT_S)


@pytest.mark.parametrize("rounds", [8])
def test_repeated_stops_give_every_slot_back(fixture, rounds):
    """Two requests may run at once. If a Stop leaked its slot, the third request in a row would be refused."""
    app = make(fixture, [(5, "delta", {"text": "x"}), ("done", {"intent": {"name": "x"}})])
    for round_number in range(1, rounds + 1):
        app.upstream.closed.clear()
        sock = post_raw(app.origin, "/api/chat/stream")
        assert wait_until(lambda n=round_number: len(app.seen) == n), "this round's request reached the API"
        time.sleep(0.05)
        sock.close()
        assert app.upstream.closed.wait(LIMIT_S)
    # Slots are released when each request ends, which is a moment after the call to Aivana closes.
    assert wait_until(lambda: app.page.post({"message": "after"}, path="/api/chat").status_code != 429, 3), "a slot was never given back"


def test_a_finished_answer_does_not_look_like_a_stop(fixture):
    app = make(fixture, [(0, "delta", {"text": "Whole answer"}), (0, "done", {"intent": {"name": "x"}})])
    response = app.page.post({"message": "Hi"}, path="/api/chat/stream")
    assert response.status_code == 200 and '"done"' in response.text
    assert not app.upstream.closed.is_set()
