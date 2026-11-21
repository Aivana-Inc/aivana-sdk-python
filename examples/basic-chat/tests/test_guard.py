"""The request guard against hostile and broken requests, on a real socket.

Each case says what a careless server would do and checks this one does not: crash, hang forever, read an
unbounded body, repeat the request back, or leave a slot taken.
"""

from __future__ import annotations

import json
import socket
import time

from .support import answer, body_of, raw, status_of


def host_of(origin: str) -> bytes:
    return origin.removeprefix("http://").encode()


def head(origin: str, extra: bytes = b"", length: int | None = None, target: bytes = b"/api/chat") -> bytes:
    lines = [b"POST " + target + b" HTTP/1.1", b"Host: " + host_of(origin), b"Origin: " + origin.encode(), b"Content-Type: application/json",
             b"Connection: close"]
    if length is not None:
        lines.append(b"Content-Length: %d" % length)
    return b"\r\n".join(lines) + b"\r\n" + extra + b"\r\n"


def alive(app) -> bool:
    return app.page.http.get("/api/config").status_code == 200


def test_malformed_requests_are_closed_or_refused_and_the_server_keeps_running(fixture):
    app = fixture()
    cases = {
        "garbage bytes": b"\x00\xff\x13garbage\r\n\r\n",
        "a 200 KB header": b"GET /x HTTP/1.1\r\nHost: %s\r\nX: %s\r\n\r\n" % (host_of(app.origin), b"a" * 200_000),
        "negative length": head(app.origin, length=-5),
        "non-numeric length": head(app.origin).replace(b"Connection: close", b"Content-Length: abc\r\nConnection: close"),
        "unknown HTTP version": b"GET / HTTP/9.9\r\nHost: %s\r\n\r\n" % host_of(app.origin),
        "no Host header": b"GET / HTTP/1.1\r\n\r\n",
        "a request line with spaces": b"GET /a b c HTTP/1.1\r\nHost: %s\r\n\r\n" % host_of(app.origin),
    }
    for name, data in cases.items():
        reply, how = raw(app.origin, data)
        assert status_of(reply) != 0 or how != "still open", f"{name}: neither answered nor closed"
        assert status_of(reply) in (0, 200, 400, 403, 404, 413, 431), (name, reply[:60])
        assert alive(app), name
    assert app.seen == []


def test_a_declared_huge_body_is_refused_without_being_read(fixture):
    app = fixture()
    started = time.monotonic()
    reply, _ = raw(app.origin, head(app.origin, length=99_999_999))
    assert status_of(reply) == 413 and json.loads(body_of(reply))["error"]["code"] == "request_too_large"
    assert time.monotonic() - started < 1, "must not wait for a body it will not accept"
    assert alive(app) and app.seen == []


def test_a_streamed_body_over_the_cap_is_cut_off(fixture):
    """No Content-Length, so the size is only known as the body arrives."""
    app = fixture()
    host, port = host_of(app.origin).decode().split(":")
    sock = socket.create_connection((host, int(port)), timeout=5)
    sock.sendall(head(app.origin, b"Transfer-Encoding: chunked\r\n"))
    piece = b"x" * 65_536
    try:
        for _ in range(8):  # 512 KiB: twice the cap
            sock.sendall(b"%x\r\n%s\r\n" % (len(piece), piece))
    except (BrokenPipeError, ConnectionResetError):
        pass
    sock.settimeout(3)
    reply = b""
    try:
        while chunk := sock.recv(65536):
            reply += chunk
    except (TimeoutError, ConnectionResetError):
        pass
    sock.close()
    assert status_of(reply) == 413 or reply == b""
    assert alive(app) and app.seen == []


def test_a_chunked_body_within_the_cap_works(fixture):
    app = fixture()
    payload = json.dumps({"message": "chunked hello"}).encode()
    split = len(payload) // 2
    chunks = b"".join(b"%x\r\n%s\r\n" % (len(part), part) for part in (payload[:split], payload[split:])) + b"0\r\n\r\n"
    reply, _ = raw(app.origin, head(app.origin, b"Transfer-Encoding: chunked\r\n") + chunks)
    assert status_of(reply) == 200 and json.loads(body_of(reply))["answer"] == "Synthetic answer"
    assert app.seen[0]["body"]["messages"] == [{"role": "user", "content": "chunked hello"}]


def test_a_body_that_never_finishes_is_given_up_on_and_its_slot_is_freed(fixture):
    app = fixture(body_timeout_s=0.5)
    started = time.monotonic()
    reply, how = raw(app.origin, head(app.origin, length=50) + b'{"mess', wait=4)
    assert status_of(reply) == 408 and json.loads(body_of(reply))["error"]["code"] == "request_timeout"
    assert 0.4 < time.monotonic() - started < 3
    assert app.seen == []
    assert app.page.post({"message": "after"}).status_code == 200, "the stalled request gave its slot back"


def test_stalled_bodies_hold_slots_only_until_the_time_limit(fixture):
    """Two stalled requests fill the two slots, so a third is told to wait, and is served once they time out."""
    app = fixture(body_timeout_s=0.8)
    host, port = host_of(app.origin).decode().split(":")
    stalled = []
    for _ in range(2):
        sock = socket.create_connection((host, int(port)), timeout=5)
        sock.sendall(head(app.origin, length=50) + b'{"mess')
        stalled.append(sock)
    time.sleep(0.2)
    try:
        assert app.page.post({"message": "blocked"}).status_code == 429
        time.sleep(1.0)
        assert app.page.post({"message": "served"}).status_code == 200
    finally:
        for sock in stalled:
            sock.close()


def test_every_refusal_carries_the_security_headers_and_the_same_envelope(fixture):
    app = fixture()
    refusals = {
        403: app.page.post({"message": "x"}, headers={"Origin": "https://other.invalid"}),
        415: app.page.post({"message": "x"}, headers={"Content-Type": "text/plain"}),
        400: app.page.post("not json"),
        404: app.page.http.get("/nothing"),
        405: app.page.http.get("/api/chat"),
    }
    for status, response in refusals.items():
        assert response.status_code == status
        assert set(response.json()) == {"error"} and set(response.json()["error"]) == {"code", "message"}
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert response.headers["referrer-policy"] == "no-referrer"
    over = raw(app.origin, head(app.origin, length=99_999_999))[0]
    assert b"content-security-policy" in over.lower() and b"nosniff" in over.lower(), "even a 413 is sent with the headers"


def test_a_page_cannot_be_framed_or_load_anything_from_elsewhere(fixture):
    csp = fixture().page.http.get("/").headers["content-security-policy"]
    for directive in ("default-src 'none'", "script-src 'self'", "style-src 'self'", "img-src 'self'", "connect-src 'self'",
                      "base-uri 'none'", "frame-ancestors 'none'", "form-action 'self'"):
        assert directive in csp
    assert "unsafe" not in csp and "http:" not in csp and "*" not in csp


def test_the_busy_limit_is_two_and_is_enforced_before_the_body_is_read(fixture):
    async def respond(entry, request, count):
        await app.upstream.wait_for_release()
        return answer()

    app = fixture(respond)
    host, port = host_of(app.origin).decode().split(":")
    held = []
    for _ in range(2):
        sock = socket.create_connection((host, int(port)), timeout=5)
        body = json.dumps({"message": "hold"}).encode()
        sock.sendall(head(app.origin, length=len(body)) + body)
        held.append(sock)
    deadline = time.monotonic() + 3
    while len(app.seen) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    started = time.monotonic()
    reply, _ = raw(app.origin, head(app.origin, length=1_000))  # promises a body it never sends
    assert status_of(reply) == 429 and time.monotonic() - started < 1, "refused at once, not after waiting for the body"
    app.upstream.release.set()
    for sock in held:
        sock.close()
