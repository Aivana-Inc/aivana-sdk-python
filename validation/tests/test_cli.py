"""The `aivana` command, validated as an external developer runs it.

Every case starts the INSTALLED console script (the one `pip install aivana` / `pipx install
aivana` puts on PATH) as a real process, with real pipes, so argument parsing, stdin handling,
stdout/stderr separation and exit codes are what a shell script would actually see.

Offline cases point AIVANA_API_BASE at a fake API on 127.0.0.1 that speaks the real wire format
(SSE on /v1/generate:stream, JSON on /v1/generate), so they need no key and cost nothing.
Live cases (marked `live`) run a handful of cheap questions against the dev host.

Expectations come from the two places a developer reads:
  README    aivana-sdk-python README.md, "Command line"
  Docs      AI Studio > Docs > Command Line (/docs/cli; source: aivana-ai-studio src/data/docsData.ts)
"""
from __future__ import annotations

import base64
import json
import os
import pty
import select
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import aivana

from conftest import LIVE_BASE

case = pytest.mark.case

AIVANA = str(Path(sys.executable).parent / "aivana")   # the console script pip installed
FAKE_KEY = "ai_test_cli_validation_not_a_real_key_0001"
# 1x1 transparent PNG
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

STAGES = [["stage", {"loading": "Selecting the right intelligence", "stage": "Selecting the right intelligence"}],
          ["stage", {"loading": "Preparing the synthesized answer", "stage": "Preparing the synthesized answer"}]]
DONE = ["done", {"finish_reason": "stop", "usage": {"input_tokens": 5, "output_tokens": 3, "credits": 0.0001}}]
DEFAULT_EVENTS = [*STAGES, ["delta", {"text": "Hello"}], ["delta", {"text": " world."}], DONE]
DEFAULT_JSON = {"id": "gen_cli_1", "request_id": "req_cli_1", "answer": "Hello world.",
                "intent": {"name": "direct_chat", "confidence": 0.9, "signal": ""},
                "finish_reason": "stop", "latency_ms": 900, "models_used": ["aivana-mmi"],
                "usage": {"input_tokens": 5, "output_tokens": 3, "cached_tokens": 0, "credits": 0.0001}}


def err_envelope(status, code, message="The server said no.", **extra):
    return status, {"error": {"type": code, "code": code, "message": message,
                              "request_id": "req_cli_err", **extra}}


# --------------------------------------------------------------------- fake API

class FakeAPI:
    """A local HTTP server standing in for the Aivana API. Records every request."""

    def __init__(self):
        self.requests: list[dict] = []
        self.events = DEFAULT_EVENTS
        self.json = DEFAULT_JSON
        self.status = 200
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {"_raw": raw.decode("utf-8", "replace")}
                api.requests.append({"path": self.path,
                                     "headers": {k.lower(): v for k, v in self.headers.items()},
                                     "body": body})
                if api.status == 200 and self.path.endswith(":stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for event, data in api.events:
                        self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
                        self.wfile.flush()
                    return
                out = json.dumps(api.json).encode()
                self.send_response(api.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def error(self, status_and_body):
        self.status, self.json = status_and_body

    @property
    def last(self) -> dict:
        assert self.requests, "the CLI made no request"
        return self.requests[-1]


@pytest.fixture
def api():
    fake = FakeAPI()
    yield fake
    fake.server.shutdown()


def clean_env(**overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AIVANA_")}
    env["PYTHONIOENCODING"] = "utf-8"
    for k, v in overrides.items():
        if v is not None:
            env[k] = v
    return env


def run(*args, env=None, stdin=subprocess.DEVNULL, input=None, timeout=30, exe=(AIVANA,)):
    """Run the installed `aivana` like a shell would. Default stdin is </dev/null."""
    if input is not None:
        stdin = None
    p = subprocess.run([*exe, *args], env=env, stdin=stdin, input=input,
                       capture_output=True, timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


@pytest.fixture
def cli(api):
    """Run against the fake API with a (fake) key set, as after `export AIVANA_API_KEY=...`."""
    def _run(*args, key=FAKE_KEY, base="fake", **kw):
        env = clean_env(AIVANA_API_KEY=key, AIVANA_API_BASE=api.base if base == "fake" else base)
        return run(*args, env=env, **kw)
    return _run


# ======================================================================= install / entry point

@case("PY-CLI-01", "CLI", "`aivana --version` runs from the installed console script and names the SDK version")
def test_version():
    code, out, err = run("--version", env=clean_env())
    assert code == 0
    assert out.strip() == f"aivana {aivana.__version__}"


@case("PY-CLI-02", "CLI", "`python -m aivana` is the same program (README)")
def test_python_m():
    code, out, _ = run("--version", env=clean_env(), exe=(sys.executable, "-m", "aivana"))
    assert code == 0 and out.strip() == f"aivana {aivana.__version__}"


DOCS_OPTIONS = ["--effort", "--shape", "--web", "--no-web", "--system", "--assistant-name",
                "--max-tokens", "--temperature", "--image", "--trace", "--json", "-q", "--quiet"]


@case("PY-CLI-03", "CLI", "`aivana --help` lists every option Docs > Command Line documents, and both env vars")
def test_help_lists_documented_options():
    code, out, _ = run("--help", env=clean_env())
    assert code == 0
    missing = [o for o in DOCS_OPTIONS if o not in out]
    assert not missing, f"documented but not in --help: {missing}"
    assert "AIVANA_API_KEY" in out and "AIVANA_API_BASE" in out


@case("PY-CLI-04", "CLI", "--help's exit-code table matches the Docs/README table (0-6, 130)")
def test_help_exit_codes():
    _, out, _ = run("--help", env=clean_env())
    table = out.split("exit codes:", 1)[1]
    for code, word in [(0, "success"), (1, "request failed"), (2, "bad usage"), (3, "authentication"),
                       (4, "rate limited"), (5, "out of credits"), (6, "temporary failure"),
                       (130, "interrupted")]:
        assert f"{code}  {word}" in table, f"exit code {code} ({word}) not in --help"


@case("PY-CLI-05", "CLI", "No model/provider option exists (Docs: 'No model picker, on purpose')")
@pytest.mark.parametrize("flag", ["--model", "--provider"])
def test_no_model_flag(cli, api, flag):
    code, out, err = cli("hi", flag, "x")
    assert code == 2 and out == "" and not api.requests
    assert "unrecognized arguments" in err


@case("PY-CLI-06", "CLI", "The bare command on a terminal prints help (exit 2); `aivana help` exits 0")
def test_bare_command_on_tty():
    leader, follower = pty.openpty()
    try:
        p = subprocess.run([AIVANA], env=clean_env(), stdin=follower, capture_output=True, timeout=15)
    finally:
        os.close(follower)
        os.close(leader)
    assert p.returncode == 2 and b"usage: aivana" in p.stdout
    code, out, _ = run("help", env=clean_env())
    assert code == 0 and "usage: aivana" in out


# ======================================================================= basic question / wire

@case("PY-CLI-10", "CLI", "Basic question: answer on stdout only, exit 0, POST /v1/generate:stream with X-API-Key")
def test_basic_question(cli, api):
    code, out, err = cli("What is 6 x 7?")
    assert code == 0
    assert out == "Hello world.\n"
    assert err == ""                    # stderr not a terminal -> no progress line
    req = api.last
    assert req["path"] == "/v1/generate:stream"
    assert req["headers"].get("x-api-key") == FAKE_KEY
    assert req["body"]["prompt"] == "What is 6 x 7?"


@case("PY-CLI-11", "CLI", "`aivana \"...\" > answer.md` saves just the answer, even with the progress line on a terminal")
def test_redirect_saves_only_answer(cli, api, tmp_path):
    leader, follower = pty.openpty()      # stderr is an interactive terminal
    env = clean_env(AIVANA_API_KEY=FAKE_KEY, AIVANA_API_BASE=api.base)
    out_file = tmp_path / "answer.md"
    try:
        with open(out_file, "wb") as fh:
            p = subprocess.run([AIVANA, "hi"], env=env, stdin=subprocess.DEVNULL, stdout=fh,
                               stderr=follower, timeout=15)
        progress = b""
        while select.select([leader], [], [], 0.2)[0]:
            chunk = os.read(leader, 4096)
            if not chunk:
                break
            progress += chunk
    finally:
        os.close(follower)
        os.close(leader)
    assert p.returncode == 0
    assert out_file.read_text() == "Hello world.\n"
    assert "Selecting the right intelligence" in progress.decode("utf-8", "replace"), \
        "Docs: a progress line shows while Aivana works (on a terminal)"


@case("PY-CLI-12", "CLI", "Every documented option reaches the wire under its SDK name (README option table)")
def test_options_on_wire(cli, api, tmp_path):
    img = tmp_path / "chart.png"
    img.write_bytes(PNG_1PX)
    code, _, err = cli("hi", "--effort", "high", "--shape", "tradeoffs", "--web", "--system", "Be brief",
                       "--assistant-name", "Acme", "--max-tokens", "50", "--temperature", "0.3",
                       "--image", str(img), "--trace")
    assert code == 0, err
    b = api.last["body"]
    assert b["effort"] == "high" and b["output_shape"] == "tradeoffs" and b["web_search"] is True
    assert b["system"] == "Be brief" and b["assistant_name"] == "Acme"
    assert b["max_tokens"] == 50 and b["temperature"] == 0.3 and b["intelligence_trace"] is True
    assert b["attachments"] == [{"mime_type": "image/png", "data": base64.b64encode(PNG_1PX).decode()}]


@case("PY-CLI-13", "CLI", "Options left off are not sent (left to Aivana); --no-web sends web_search=false")
def test_unset_options_and_no_web(cli, api):
    cli("hi")
    # `mode` is the SDK's fixed product constant ("aivana_mmi"), not a caller option;
    # conformance/cli.json expects exactly these keys too.
    assert set(api.last["body"]) == {"prompt", "metadata", "mode"}
    assert api.last["body"]["mode"] == "aivana_mmi"
    cli("hi", "--no-web")
    assert api.last["body"]["web_search"] is False


@case("PY-CLI-14", "CLI", "Reserved word is refused with a hint; `aivana ask ...` is the way around it (README)")
def test_reserved_word(cli, api):
    code, out, err = cli("chat", "about", "pricing")
    assert code == 2 and not api.requests and "aivana ask chat about pricing" in err
    code, out, _ = cli("ask", "chat", "about", "pricing")
    assert code == 0 and api.last["body"]["prompt"] == "chat about pricing"


@case("PY-CLI-15", "CLI", "Abbreviated options are refused (`--temp` is not --temperature)")
def test_no_abbreviations(cli, api):
    code, _, _ = cli("hi", "--temp", "0.5")
    assert code == 2 and not api.requests


# ======================================================================= stdin / pipes

@case("PY-CLI-20", "CLI", "Piped text is sent ahead of the question (`git diff | aivana \"Review this change\"`)")
def test_pipe_ahead_of_question(cli, api):
    code, _, _ = cli("Review this change", input=b"diff --git a/x b/x\n+new line\n")
    assert code == 0
    assert api.last["body"]["prompt"] == "diff --git a/x b/x\n+new line\n\nReview this change"


@case("PY-CLI-21", "CLI", "Piped text alone is the question; `aivana \"...\" < contract.txt` works")
def test_pipe_alone_and_file_redirect(cli, api, tmp_path):
    code, _, _ = cli(input=b"Summarize: the sky is blue.")
    assert code == 0 and api.last["body"]["prompt"] == "Summarize: the sky is blue."
    f = tmp_path / "contract.txt"
    f.write_text("Clause 1. Payment in 30 days.\n")
    with open(f, "rb") as fh:
        code, _, _ = cli("Summarize the three biggest risks", stdin=fh)
    assert code == 0
    assert api.last["body"]["prompt"] == "Clause 1. Payment in 30 days.\n\nSummarize the three biggest risks"


@case("PY-CLI-22", "CLI", "Docs: with nothing piped, `< /dev/null` answers at once (no 3 s wait, no note)")
def test_dev_null_no_wait(cli, api):
    t = time.monotonic()
    code, _, err = cli("hi", stdin=subprocess.DEVNULL)
    assert code == 0 and time.monotonic() - t < 2.5 and "note" not in err


@case("PY-CLI-23", "CLI", "Docs: an open-but-silent stdin waits about 3 s, says so on stderr, then sends just the question")
def test_silent_stdin_waits(api):
    env = clean_env(AIVANA_API_KEY=FAKE_KEY, AIVANA_API_BASE=api.base)
    t = time.monotonic()
    p = subprocess.Popen([AIVANA, "hi"], env=env, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        _, err = _wait_then_close(p)
    finally:
        p.kill()
    elapsed = time.monotonic() - t
    assert p.returncode == 0
    assert 2.5 <= elapsed < 10, f"waited {elapsed:.1f}s; Docs say up to 3 seconds"
    assert "no piped input arrived within 3s" in err and "/dev/null" in err
    assert api.last["body"]["prompt"] == "hi"


def _wait_then_close(p):
    """Keep stdin open (never write), wait for the process, then close the pipe."""
    out, err = p.stdout.read(), p.stderr.read()
    p.wait(timeout=15)
    p.stdin.close()
    return out.decode(), err.decode()


@case("PY-CLI-24", "CLI", "Binary piped input is refused locally with a pointer to --image (exit 2)")
def test_binary_stdin(cli, api):
    code, out, err = cli("Describe", input=PNG_1PX + b"\xff\xfe\x00")
    assert code == 2 and not api.requests and "--image" in err


# ======================================================================= --json / --trace / --image

@case("PY-CLI-30", "CLI", "--json waits for the whole response (POST /v1/generate) and prints parseable JSON")
def test_json(cli, api):
    code, out, err = cli("What is 6 x 7?", "--json")
    assert code == 0, err
    assert api.last["path"] == "/v1/generate"
    data = json.loads(out)
    assert data["answer"] == "Hello world." and data["usage"]["output_tokens"] == 3
    assert err == ""


@case("PY-CLI-34", "CLI", "A 200 --json response the SDK cannot parse ends in a clean `aivana: error:` (exit 1), not a traceback")
@pytest.mark.xfail(reason="F17: a 200 body missing a required field (e.g. intent) raises pydantic.ValidationError, "
                   "which escapes the CLI as a raw Python traceback; it is not an AivanaError either")
def test_json_unparseable_200(cli, api):
    api.json = {k: v for k, v in DEFAULT_JSON.items() if k != "intent"}
    rc, out, err = cli("hi", "--json")
    assert "Traceback" not in err
    assert rc == 1 and err.startswith("aivana: error:")


@case("PY-CLI-31", "CLI", "--trace prints the Intelligence Trace on stderr after the answer; stdout stays the answer")
def test_trace(cli, api):
    api.events = [
        ["trace", {"step": {"id": "u", "title": "Understanding Request", "status": "ok", "at_ms": 1200}}],
        *STAGES, ["delta", {"text": "The answer."}],
        ["trace", {"status": "completed",
                   "steps": [{"id": "u", "title": "Understanding Request", "status": "ok", "at_ms": 1200},
                             {"id": "s", "title": "Final Synthesis", "status": "ok", "at_ms": 8450}],
                   "summary": {"route": "2-model verification", "perspectives": 2,
                               "fresh_data": "not_required"}}],
        DONE]
    code, out, err = cli("hi", "--trace")
    assert code == 0
    assert out == "The answer.\n"
    assert "Intelligence Trace" in err and "Understanding Request" in err and "Final Synthesis  8.5s" in err
    assert "Intelligence Trace" not in out
    assert api.last["body"]["intelligence_trace"] is True


@case("PY-CLI-32", "CLI", "--image: non-image files are refused locally (exit 2) with how to send a document instead")
@pytest.mark.parametrize("name", ["report.pdf", "notes.docx"])
def test_image_rejects_documents(cli, api, tmp_path, name):
    (tmp_path / name).write_bytes(b"%PDF-1.4")
    code, out, err = cli("Summarize", "--image", str(tmp_path / name))
    assert code == 2 and not api.requests
    assert "only PNG, JPEG, WebP and GIF" in err


@case("PY-CLI-33", "CLI", "--image with a missing file names the file (exit 2, nothing sent)")
def test_image_missing(cli, api, tmp_path):
    code, _, err = cli("hi", "--image", str(tmp_path / "nope.png"))
    assert code == 2 and not api.requests and "nope.png" in err


# ======================================================================= errors / exit codes

@case("PY-CLI-40", "CLI", "No AIVANA_API_KEY: exit 3 before any request, with how to set it")
def test_no_key(cli, api):
    code, out, err = cli("hi", key=None)
    assert code == 3 and out == "" and not api.requests
    assert "no API key found" in err and "export AIVANA_API_KEY" in err


@case("PY-CLI-41", "CLI", "Each documented HTTP error maps to the documented exit code, message + request id on stderr")
@pytest.mark.parametrize("status,code,exit_code", [
    (401, "invalid_api_key", 3), (403, "forbidden", 3), (429, "rate_limit_exceeded", 4),
    (402, "insufficient_credit", 5), (502, "upstream_error", 6), (504, "timeout", 6),
    (503, "config_unavailable", 6), (500, "internal_error", 1)])
@pytest.mark.parametrize("mode", ["stream", "json"])
def test_http_errors(cli, api, status, code, exit_code, mode):
    api.error(err_envelope(status, code))
    args = ["hi"] + (["--json"] if mode == "json" else [])
    rc, out, err = cli(*args)
    assert rc == exit_code, f"HTTP {status} {code} ({mode}): exit {rc}, docs say {exit_code}\n{err}"
    assert out == ""
    assert "The server said no. (request id: req_cli_err)" in err


@case("PY-CLI-42", "CLI", "A 422 validation error names the flag to fix (exit 1)")
def test_validation_names_flag(cli, api):
    api.error(err_envelope(422, "invalid_request", "Request validation failed.",
                           details=[{"loc": ["body", "temperature"], "msg": "Input should be less than or equal to 2",
                                     "type": "less_than_equal"}]))
    rc, _, err = cli("hi", "--temperature", "3")
    assert rc == 1 and "--temperature: Input should be less than or equal to 2" in err


@case("PY-CLI-43", "CLI", "Bad usage exits 2 with no request (unknown --effort, non-number --max-tokens, no question)")
@pytest.mark.parametrize("args", [["hi", "--effort", "extreme"], ["hi", "--max-tokens", "lots"], []])
def test_usage_errors(cli, api, args):
    rc, out, _ = cli(*args)
    assert rc == 2 and out == "" and not api.requests


@case("PY-CLI-44", "CLI", "Unreachable API: exit 6 ('safe to retry')")
def test_unreachable(cli, api):
    rc, _, err = cli("hi", base="http://127.0.0.1:9")
    assert rc == 6 and "couldn't reach" in err and "safe to retry" in err


@case("PY-CLI-45", "CLI", "An error frame inside a 200 stream exits 6, and partial text is flagged as incomplete")
def test_stream_error_frame(cli, api):
    api.events = [*STAGES, ["delta", {"text": "Partial"}], ["error", {"type": "upstream_error", "message": "x"}],
                  ["done", {"finish_reason": "error", "usage": {}}]]
    rc, out, err = cli("hi")
    assert rc == 6 and out == "Partial\n" and "The text above is incomplete." in err


@case("PY-CLI-46", "CLI", "A cut-off answer (finish_reason=length) says so on stderr")
def test_length_note(cli, api):
    api.events = [["delta", {"text": "Cut"}], ["done", {"finish_reason": "length", "usage": {}}]]
    rc, out, err = cli("hi", "--max-tokens", "5")
    assert rc == 0 and out == "Cut\n" and "cut off at the length limit" in err


@case("PY-CLI-47", "CLI", "The API key never appears in stdout or stderr, on success or failure")
def test_key_never_printed(cli, api):
    outputs = [cli("hi"), cli("hi", "--json")]
    api.error(err_envelope(401, "invalid_api_key"))
    outputs += [cli("hi"), cli("hi", "--json")]
    for _, out, err in outputs:
        assert FAKE_KEY not in out and FAKE_KEY not in err


# ======================================================================= environment / API base

@case("PY-CLI-50", "CLI", "AIVANA_API_BASE that is not a URL is refused locally (exit 2)")
def test_bad_base(cli, api):
    rc, _, err = cli("hi", base="api.aivana.ai")
    assert rc == 2 and "must be a full URL" in err


@case("PY-CLI-51", "CLI", "Plain http:// to a non-local host warns the key travels unencrypted")
def test_plain_http_warns(cli):
    rc, _, err = cli("hi", base="http://aivana-validation.invalid:9")
    assert "travels unencrypted" in err


@case("PY-CLI-52", "CLI", "Plain http:// to localhost is ordinary local development (no warning)")
def test_localhost_no_warning(cli):
    rc, _, err = cli("hi")
    assert rc == 0 and "unencrypted" not in err


@case("PY-CLI-53", "CLI", "With AIVANA_API_BASE unset the CLI calls the documented default (https://api.aivana.ai)")
def test_default_base_offline():
    # Point the default at nowhere by blocking DNS is not portable; instead read where a request
    # would go from the SDK the CLI is built on, as installed.
    code = ("import aivana.client as c, aivana.cli as cli, sys; "
            "print(c.api_base); print('https://api.aivana.ai' in cli.EPILOG)")
    p = subprocess.run([sys.executable, "-c", code], env=clean_env(), capture_output=True, text=True)
    base, in_help = p.stdout.split()
    assert base == "https://api.aivana.ai" and in_help == "True"


# ======================================================================= live (dev host)

LIVE_ARGS = ["--effort", "low", "--max-tokens", "60", "-q"]


@pytest.fixture
def live_cli(live):
    key = os.environ["AIVANA_API_KEY"]

    def _run(*args, base=LIVE_BASE, key=key, **kw):
        return run(*args, env=clean_env(AIVANA_API_KEY=key, AIVANA_API_BASE=base), timeout=120, **kw)
    return _run


def cli_evidence(evidence, rc, out, err, **extra):
    evidence(exit=rc, stdout_preview=out[:200], stderr_preview=err[:400], **extra)


@case("PY-CLI-L01", "CLI", "Live: basic question streams an answer to stdout, nothing on stderr, exit 0")
@pytest.mark.live
def test_live_basic(live_cli, evidence):
    rc, out, err = live_cli("Reply with the single word: ok", *LIVE_ARGS)
    cli_evidence(evidence, rc, out, err)
    assert rc == 0 and out.strip() and err == ""


@case("PY-CLI-L02", "CLI", "Live: --json prints a GenerateResponse with answer, usage and request_id")
@pytest.mark.live
def test_live_json(live_cli, evidence):
    rc, out, err = live_cli("Reply with the single word: ok", *LIVE_ARGS, "--json")
    data = json.loads(out) if rc == 0 else {}
    cli_evidence(evidence, rc, "", err, request_id=data.get("request_id"), usage=data.get("usage"),
                 finish_reason=data.get("finish_reason"))
    assert rc == 0 and data["answer"] and data["usage"]["output_tokens"] >= 1 and data["request_id"]


@case("PY-CLI-L03", "CLI", "Live: --trace shows the Intelligence Trace on stderr only, with no model/provider names")
@pytest.mark.live
def test_live_trace(live_cli, evidence):
    rc, out, err = live_cli("Is Postgres or DynamoDB better for a write-heavy API? One sentence.",
                            *LIVE_ARGS, "--trace")
    cli_evidence(evidence, rc, out, err)
    assert rc == 0 and "Intelligence Trace" in err and "Intelligence Trace" not in out
    lowered = err.lower()
    for leak in ("gpt", "claude", "gemini", "openai", "anthropic", "llama", "mistral", "bedrock"):
        assert leak not in lowered, f"trace names {leak!r}"


@case("PY-CLI-L04", "CLI", "Live: piped text is answered (`echo ... | aivana \"...\"`)")
@pytest.mark.live
def test_live_pipe(live_cli, evidence):
    rc, out, err = live_cli("What is the secret word in the text above? Reply with just the word.",
                            *LIVE_ARGS, input=b"The secret word is: pineapple.")
    cli_evidence(evidence, rc, out, err)
    assert rc == 0 and "pineapple" in out.lower()


@case("PY-CLI-L05", "CLI", "Live: an invalid key exits 3 with a request id, and the key is not echoed")
@pytest.mark.live
def test_live_invalid_key(live_cli, evidence):
    bad = "ai_test_definitely_not_a_real_key_000"
    rc, out, err = live_cli("ping", "-q", key=bad)
    cli_evidence(evidence, rc, out, err)
    assert rc == 3 and out == "" and "request id: req_" in err and bad not in err


@case("PY-CLI-L06", "CLI", "Live: `--shape extract --json` (Docs/README example) returns a structured result")
@pytest.mark.live
def test_live_extract(live_cli, evidence):
    rc, out, err = live_cli("Extract the invoice number and total", "--shape", "extract", "--json",
                            "--effort", "low", "-q", input=b"Invoice INV-2041. Total due: $1,250.00.")
    data = json.loads(out) if rc == 0 else {}
    cli_evidence(evidence, rc, "", err, structured=data.get("structured"),
                 structured_error=data.get("structured_error"))
    assert rc == 0 and (data.get("structured") is not None or data.get("structured_error") is not None)


@case("PY-CLI-L07", "CLI", "Live: --image attaches a PNG and the request is accepted")
@pytest.mark.live
def test_live_image(live_cli, evidence, tmp_path):
    img = tmp_path / "pixel.png"
    img.write_bytes(PNG_1PX)
    rc, out, err = live_cli("Describe this image in five words or fewer.", *LIVE_ARGS, "--image", str(img))
    cli_evidence(evidence, rc, out, err)
    assert rc == 0 and out.strip()


@case("PY-CLI-L08", "CLI", "Live: a test key with AIVANA_API_BASE unset (production) exits 3 and says the key is from another environment")
@pytest.mark.live
@pytest.mark.xfail(strict=False, reason="F2: refusing ai_test_ keys on api.aivana.ai is by design (Docs > API Keys), but the CLI "
                   "says 'Invalid or expired API key. Generate a new key' and suggests `export AIVANA_API_KEY=ai_live_...`")
def test_live_default_base(live_cli, evidence):
    rc, out, err = live_cli("Reply with the single word: ok", *LIVE_ARGS, base=None)
    cli_evidence(evidence, rc, out, err, base="(unset -> default)")
    assert rc == 3
    assert "environment" in err.lower() or "test key" in err.lower(), err
