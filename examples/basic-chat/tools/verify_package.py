"""Check an extracted copy of the standalone download, the way a customer would run it.

    python tools/verify_package.py EXTRACTED_FOLDER

Run it with the Python whose environment has the starter's requirements installed (the "Basic Chat download" workflow makes
a fresh virtual environment from the extracted requirements.txt for each operating system and Python version). It talks to a
stand-in for the Aivana API on 127.0.0.1, so it spends no credit and needs no key.

It checks: setup and doctor, the page and the files that must never be served, the Blueprint modes (none, session history,
no history) with what really reaches the API, a streamed answer, that Stop reaches the API call, and that an unsupported
Blueprint stops startup. Standard library only, so it cannot depend on anything the package does not ship.
"""

from __future__ import annotations

import http.client
import json
import os
import select
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SOURCE_LINK = "https://github.com/Aivana-Inc/aivana-sdk-python/tree/main/examples/basic-chat"
ANSWER = "Packaged fixture answer"


def fail(message: str) -> None:
    print(f"FAIL  {message}", file=sys.stderr)
    raise SystemExit(1)


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def passed(message: str) -> None:
    print(f"ok    {message}", flush=True)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeAPI:
    """Records what the starter sends and answers like Aivana does."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.closed = threading.Event()  # the starter dropped its call before the answer was complete
        api = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"  # each response ends when the connection closes

            def log_message(self, *args) -> None:
                pass

            def client_gone(self) -> bool:
                try:
                    readable, _, _ = select.select([self.connection], [], [], 0.05)
                    return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
                except OSError:
                    return True

            def do_POST(self) -> None:
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}")
                api.requests.append({"path": self.path, "body": body})
                if self.path == "/v1/generate":
                    raw = json.dumps({"id": "gen_1", "answer": ANSWER, "intent": {"name": "fixture", "confidence": 0.9},
                                      "pending_action": "next"}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                elif self.path == "/v1/generate:stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    last = (body.get("messages") or [{}])[-1].get("content", "")
                    if "HOLD-OPEN" in last:  # "Thinking": nothing is sent until the starter hangs up (or 20 s pass)
                        deadline = time.monotonic() + 20
                        while time.monotonic() < deadline:
                            if self.client_gone():
                                api.closed.set()
                                return
                        return
                    for name, data in (("delta", {"text": "Packaged "}), ("delta", {"text": "stream answer"}),
                                       ("done", {"intent": {"name": "fixture"}, "usage": {"input_tokens": 3, "output_tokens": 4}})):
                        self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                        self.wfile.flush()
                else:
                    self.send_response(404)
                    self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reset(self) -> None:
        self.requests.clear()
        self.closed.clear()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def clean_env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AIVANA_") and k != "PORT"}
    env.update(extra)
    return env


def run(root: Path, expected: int, *args: str) -> subprocess.CompletedProcess:
    """One command of the starter (python -m basic_chat ...), configured only through the environment."""
    done = subprocess.run(
        [sys.executable, "-m", "basic_chat", *args], cwd=root, capture_output=True, text=True, timeout=90,
        env=clean_env(AIVANA_API_KEY="synthetic-fixture-key", AIVANA_API_BASE="http://127.0.0.1:1", PORT="3006", AIVANA_BLUEPRINT_FILE=""),
    )
    check(done.returncode == expected, f"python -m basic_chat {' '.join(args)}: exit {done.returncode}, expected {expected}\n{done.stderr}")
    return done


class RunningApp:
    def __init__(self, root: Path, api_url: str) -> None:
        self.port = free_port()
        self.origin = f"http://127.0.0.1:{self.port}"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "basic_chat"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=clean_env(AIVANA_API_KEY="synthetic-fixture-key", AIVANA_API_BASE=api_url, PORT=str(self.port), AIVANA_BLUEPRINT_FILE=""),
        )
        deadline = time.monotonic() + 60
        while True:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.5).close()
                return
            except OSError:
                if self.proc.poll() is not None:
                    fail(f"the starter exited while starting: {self.proc.communicate()[1]}")
                if time.monotonic() > deadline:
                    self.stop()
                    fail("the starter did not start within 60 seconds")
                time.sleep(0.1)

    def request(self, method: str, path: str, body: object = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Origin": self.origin, "Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def stop(self) -> str:
        if self.proc.poll() is None:
            self.proc.terminate()
        try:
            return self.proc.communicate(timeout=20)[1]
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return self.proc.communicate()[1]


def check_mode(root: Path, api: FakeAPI, sample: dict, mode: str | None) -> None:
    label = f"blueprint, history {mode}" if mode else "default settings"
    api.reset()
    app = RunningApp(root, api.url)
    try:
        status, page = app.request("GET", "/")
        check(status == 200 and b"Basic AI Chat" in page, f"{label}: the page is not served")
        check(SOURCE_LINK.encode() in page, f"{label}: the page's source link does not point at the Python starter")
        for path in ("/.env", "/blueprint-definition.json", "/basic_chat/app.py", "/requirements.txt", "/MANIFEST.json", "/README.md"):
            check(app.request("GET", path)[0] == 404, f"{label}: {path} must not be served")
        config = json.loads(app.request("GET", "/api/config")[1])
        expected = {"blueprintLoaded": bool(mode), "history": mode or "session", "webSearch": False}
        if mode:
            expected["blueprint"] = {"purpose": sample["purpose"].strip(), "effort": sample["configuration"]["effort"],
                                     "maxTokens": sample["configuration"]["max_tokens"]}
        check(config == expected, f"{label}: /api/config is {config}")
        check(sample["configuration"]["system"] not in json.dumps(config), f"{label}: the Blueprint instructions reached the browser")

        status, raw = app.request("POST", "/api/chat", {"message": "Hello", "history": [
            {"role": "user", "content": "Earlier"}, {"role": "assistant", "content": "Answer"}], "context": {"pendingAction": "earlier"}})
        answer = json.loads(raw)
        check(status == 200 and answer.get("answer") == ANSWER, f"{label}: chat answered {status} {raw[:120]!r}")
        check(len(api.requests) == 1, f"{label}: expected one request to the API, saw {len(api.requests)}")
        wire = api.requests[0]["body"]
        check(wire.get("system") == (sample["configuration"]["system"] if mode else None), f"{label}: the system instructions on the wire are wrong")
        check(len(wire["messages"]) == (1 if mode == "none" else 3), f"{label}: {len(wire['messages'])} messages on the wire")
        check(wire.get("pending_action") == (None if mode == "none" else "earlier"), f"{label}: pending_action on the wire is wrong")
        if mode == "none":
            check(answer["context"] == {}, f"{label}: a no-history Blueprint returned continuation context")
        passed(f"{label}: page, hidden files, config, and what reaches the API")

        if mode is None:
            api.reset()
            status, raw = app.request("POST", "/api/chat/stream", {"message": "Stream please"})
            events = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
            check(status == 200 and [e["event"] for e in events] == ["delta", "delta", "done"], f"streaming: events were {events}")
            check("".join(e["data"]["text"] for e in events[:2]) == "Packaged stream answer", "streaming: the text is wrong")
            check(events[-1]["data"]["usage"] == {"inputTokens": 3, "outputTokens": 4}, "streaming: usage was not forwarded as counts only")
            passed("streaming: text arrives, then done with token counts only")

            api.reset()
            body = json.dumps({"message": "HOLD-OPEN"}).encode()
            sock = socket.create_connection(("127.0.0.1", app.port), timeout=10)
            sock.sendall(b"POST /api/chat/stream HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nOrigin: %s\r\nContent-Type: application/json\r\n"
                         b"Content-Length: %d\r\n\r\n%s" % (app.port, app.origin.encode(), len(body), body))
            deadline = time.monotonic() + 15
            while not api.requests and time.monotonic() < deadline:
                time.sleep(0.05)
            check(bool(api.requests), "Stop: the request never reached the API")
            time.sleep(0.3)  # still "Thinking": no text has been sent
            sock.close()  # the browser's Stop
            check(api.closed.wait(8), "Stop: the call to the API was still open 8 seconds after the browser left")
            passed("Stop before the first word reaches the API call")
    finally:
        stderr = app.stop()
        check("Traceback" not in stderr, f"{label}: the starter printed a traceback:\n{stderr}")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: python tools/verify_package.py EXTRACTED_FOLDER", file=sys.stderr)
        return 2
    root = Path(argv[0]).resolve()
    check((root / "basic_chat" / "app.py").is_file(), f"{root} does not look like the extracted download")
    sample = json.loads((root / "blueprints" / "landscaping.example.json").read_text(encoding="utf-8"))
    definition = root / "blueprint-definition.json"
    api = FakeAPI()
    try:
        run(root, 0, "setup")
        check((root / ".env").is_file(), "setup did not create .env")
        passed("setup creates .env")
        run(root, 0, "doctor")
        passed("doctor passes with default settings")
        check_mode(root, api, sample, None)
        for mode in ("session", "none"):
            sample["conversation"]["history"] = mode
            definition.write_text(json.dumps(sample), encoding="utf-8")
            run(root, 0, "doctor")
            check_mode(root, api, sample, mode)
        sample["knowledge"] = {"source_set_id": "unavailable", "requirement": "required"}
        definition.write_text(json.dumps(sample), encoding="utf-8")
        check("Sources" in run(root, 1, "doctor").stderr, "doctor must refuse a Blueprint with Sources, naming them")
        check("Sources" in run(root, 1).stderr, "startup must refuse a Blueprint with Sources, naming them")
        passed("an unsupported Blueprint (with Sources) stops doctor and startup")
        print("Extracted download passed setup, default and Blueprint chat, history policy, streaming, Stop and unsupported-file refusal. No billed calls.")
        return 0
    finally:
        definition.unlink(missing_ok=True)
        api.stop()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
