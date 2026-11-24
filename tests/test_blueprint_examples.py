"""Execute candidate examples through real HTTP without contacting Aivana."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = Path(__file__).parents[1]
FIXTURE = json.loads((ROOT / "conformance/blueprints.json").read_text())


@pytest.mark.parametrize("version", ["3", "latest"])
@pytest.mark.parametrize("streaming", [False, True])
def test_example_http(version, streaming):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            expected = f"/v1/blueprints/{FIXTURE['id']}/versions/{version}/generate" + (":stream" if streaming else "")
            if self.path != expected or self.headers.get("X-API-Key") != "synthetic-not-a-real-key":
                self.send_error(400)
                return
            if set(body) != {"prompt", "intelligence_trace"}:
                self.send_error(422)
                return
            calls.append(self.path)
            result = json.loads(json.dumps(FIXTURE["response"]))
            result["blueprint"]["version"] = 7 if version == "latest" else 3
            frames = [("delta", {"text": result["answer"]}), ("done", result)]
            content = ("".join(f"event: {event}\r\ndata: {json.dumps(data)}\r\n\r\n" for event, data in frames)
                       if streaming else json.dumps(result)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        environment = {**os.environ, "PYTHONPATH": str(ROOT), "AIVANA_API_KEY": "synthetic-not-a-real-key",
                       "AIVANA_API_BASE": f"http://127.0.0.1:{server.server_port}", "AIVANA_BLUEPRINT_ID": FIXTURE["id"],
                       "AIVANA_BLUEPRINT_VERSION": version, "NO_PROXY": "127.0.0.1,localhost"}
        result = subprocess.run([sys.executable, str(ROOT / "examples/blueprints/invoke.py")]
                                + (["--stream"] if streaming else []), env=environment,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert "Resolved Blueprint:" in result.stdout
        assert FIXTURE["id"] in result.stdout
        assert len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
