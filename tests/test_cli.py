"""The `aivana` command: what reaches the wire, what reaches the terminal, and
which exit code a script sees.

Every test drives `cli.main()` against a fake API (httpx.MockTransport), so the
real SDK runs underneath exactly as it would against the service: its request
body, its SSE parser, its error mapping. Response bodies are generators on
purpose. httpx pre-reads a body built from bytes, and that is how the streaming
error bug fixed alongside this CLI stayed hidden (see test_errors.py).

    python3 -m pytest tests/ -q
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aivana import cli  # noqa: E402
from aivana import client as sdk  # noqa: E402

KEY = "ai_live_test_key_not_real"

STAGES = [("stage", {"loading": s, "stage": s}) for s in (
    "Selecting the right intelligence",
    "Reviewing multiple perspectives",
    "Resolving disagreements",
    "Preparing the synthesized answer",
)]


def _sse(*frames: tuple[str, dict]) -> bytes:
    return "".join(f"event: {event}\ndata: {json.dumps(data)}\n\n"
                   for event, data in frames).encode()


def _answer(*parts: str, finish_reason: str = "stop") -> bytes:
    """A stream shaped like /v1/generate:stream's: four stages, deltas, done."""
    return _sse(*STAGES, *[("delta", {"text": p}) for p in parts],
                ("done", {"finish_reason": finish_reason, "model": "aivana-mmi",
                          "usage": {"input_tokens": 5, "output_tokens": 7,
                                    "credits": 0.0001}}))


def _error_body(code: str, message: str = "The server said no.", **extra) -> bytes:
    return json.dumps({"error": {"type": code, "code": code, "message": message,
                                 "request_id": "req_123", **extra}}).encode()


class FakeAPI:
    """Records every request and answers with whatever the test set up."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.body = _answer("Hello", " world.")   # bytes, or a generator function
        self.raises: BaseException | None = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        stream = request.url.path.endswith(":stream") and self.status == 200
        body = self.body() if callable(self.body) else (b for b in [self.body])
        return httpx.Response(
            self.status,
            headers={"content-type": "text/event-stream" if stream else "application/json"},
            content=body,
        )

    @property
    def sent(self) -> dict:
        return json.loads(self.requests[-1].content)


class Stdin(io.StringIO):
    def __init__(self, text: str = "", *, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def api(monkeypatch):
    fake = FakeAPI()
    real = httpx.Client
    monkeypatch.setattr(sdk.httpx, "Client",
                        lambda **kw: real(transport=httpx.MockTransport(fake.handle), **kw))
    # The CLI writes the key and base into the SDK's module-level config; these
    # restore both afterwards so no other test inherits them.
    monkeypatch.setattr(sdk, "api_key", None)
    monkeypatch.setattr(sdk, "api_base", sdk.api_base)
    monkeypatch.setenv("AIVANA_API_KEY", KEY)
    monkeypatch.delenv("AIVANA_API_BASE", raising=False)
    monkeypatch.setattr(sys, "stdin", Stdin(tty=True))
    return fake


@pytest.fixture
def pipe(monkeypatch):
    """stdin as a real OS pipe; the test gets the write end."""
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "r")
    monkeypatch.setattr(sys, "stdin", reader)
    yield write_fd
    reader.close()
    try:
        os.close(write_fd)
    except OSError:
        pass                                    # the test already closed it


def ask(capsys, *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


# --- the happy path -----------------------------------------------------------

def test_the_answer_streams_to_stdout_and_nothing_else(api, capsys):
    code, out, err = ask(capsys, "Say hello")
    assert code == cli.EXIT_OK
    assert out == "Hello world.\n"
    # stderr is not a terminal under pytest, so not even a progress line is drawn.
    assert err == ""


def test_it_is_the_same_public_call_an_application_makes(api, capsys):
    ask(capsys, "Compare", "Postgres", "and", "DynamoDB",
        "--effort", "high", "--shape", "tradeoffs", "--web",
        "--max-tokens", "300", "--temperature", "0.2",
        "--system", "Answer in bullets.", "--assistant-name", "Acme Copilot")
    request = api.requests[-1]
    assert str(request.url) == "https://developers.aivana.ai/v1/generate:stream"
    assert request.headers["x-api-key"] == KEY
    assert api.sent == {
        "mode": "aivana_mmi",               # the SDK's own constant, read nowhere
        "prompt": "Compare Postgres and DynamoDB",
        "effort": "high",
        "output_shape": "tradeoffs",
        "web_search": True,
        "max_tokens": 300,
        "temperature": 0.2,
        "system": "Answer in bullets.",
        "assistant_name": "Acme Copilot",
        "metadata": {"request_source": "cli-python"},
    }


def test_options_left_unset_are_left_to_aivana(api, capsys):
    ask(capsys, "hi")
    assert set(api.sent) == {"mode", "prompt", "metadata"}


def test_no_web_reaches_the_wire_as_false(api, capsys):
    """--web, --no-web and neither are three different requests, not two."""
    ask(capsys, "hi", "--no-web")
    assert api.sent["web_search"] is False


def test_options_may_sit_among_the_words(api, capsys):
    ask(capsys, "why", "is", "--effort", "low", "this", "slow")
    assert api.sent["prompt"] == "why is this slow"
    assert api.sent["effort"] == "low"


def test_piped_text_goes_ahead_of_the_question(api, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", Stdin("KeyError: 'id'\n", tty=False))
    ask(capsys, "What's causing this?")
    assert api.sent["prompt"] == "KeyError: 'id'\n\nWhat's causing this?"


def test_piped_text_alone_is_the_question(api, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", Stdin("Summarize: the sky is blue.", tty=False))
    code, _, _ = ask(capsys)
    assert code == cli.EXIT_OK
    assert api.sent["prompt"] == "Summarize: the sky is blue."


def test_input_from_a_real_pipe_is_read(api, capsys, pipe):
    os.write(pipe, b"ERROR: deadlock detected\n")
    os.close(pipe)
    ask(capsys, "What's causing this?")
    assert api.sent["prompt"] == "ERROR: deadlock detected\n\nWhat's causing this?"


@pytest.mark.skipif(os.name == "nt", reason="select() cannot watch a pipe on Windows")
def test_a_pipe_nobody_writes_to_cannot_hang_the_command(api, capsys, monkeypatch, pipe):
    """An agent's shell, `ssh host aivana ...`, a subprocess that inherited its
    parent's stdin: open, never written, never closed. Found the hard way: the
    first end-to-end run of this CLI hung on exactly this."""
    monkeypatch.setattr(cli, "STDIN_WAIT_S", 0.2)
    code, _, err = ask(capsys, "Just the question")
    assert code == cli.EXIT_OK
    assert api.sent["prompt"] == "Just the question"
    assert "no piped input arrived within 0.2s" in err
    assert "< /dev/null" in err


def test_an_image_is_sent_as_base64(api, capsys, tmp_path):
    png = tmp_path / "chart.png"
    png.write_bytes(b"\x89PNG not really")
    ask(capsys, "What's in this?", "--image", str(png))
    assert api.sent["attachments"] == [{
        "mime_type": "image/png",
        "data": base64.b64encode(b"\x89PNG not really").decode(),
    }]


def test_json_prints_the_whole_response(api, capsys):
    api.body = json.dumps({
        "id": "gen_1", "answer": "42",
        "intent": {"name": "direct_chat", "confidence": 0.9, "signal": ""},
        "models_used": ["aivana-mmi"], "latency_ms": 900,
        "usage": {"input_tokens": 3, "output_tokens": 1, "cached_tokens": 0,
                  "credits": 0.0},
    }).encode()
    code, out, _ = ask(capsys, "What is 6 x 7?", "--json")
    assert code == cli.EXIT_OK
    assert api.requests[-1].url.path == "/v1/generate"
    assert json.loads(out)["answer"] == "42"


def test_progress_draws_on_a_terminal_and_is_wiped_before_the_answer(
        api, capsys, monkeypatch):
    terminal = Terminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    code, out, _ = ask(capsys, "hi")
    drawn = terminal.getvalue()
    assert code == cli.EXIT_OK and out == "Hello world.\n"
    assert "Selecting the right intelligence…" in drawn
    assert "Preparing the synthesized answer…" in drawn
    assert drawn.endswith("\r"), "the status line must be cleared, not left behind"


def test_the_trace_goes_to_stderr_and_waits_for_the_answer(api, capsys):
    def step(sid, title, detail, status, at_ms=None):
        return {"id": sid, "title": title, "detail": detail,
                "status": status, "at_ms": at_ms}

    understood = step("understanding", "Understanding Request", "Multi-part request",
                      "ok", 1200)
    synthesized = step("synthesis", "Final Synthesis", "Findings combined", "ok", 8100)
    api.body = _sse(
        ("trace", {"step": {**understood, "status": "running", "at_ms": None}}),
        ("trace", {"step": understood}),
        *STAGES,
        ("delta", {"text": "The answer."}),
        ("trace", {"step": {**synthesized, "status": "running", "at_ms": None}}),
        ("trace", {"step": synthesized}),
        ("trace", {"status": "completed", "steps": [understood, synthesized],
                   "summary": {"route": "2-model verification", "perspectives": 2,
                               "fresh_data": "not_required"},
                   "why_this_route": ["A second perspective adds confidence."]}),
        ("done", {"finish_reason": "stop", "usage": {}}),
    )
    code, out, err = ask(capsys, "hi", "--trace")
    assert code == cli.EXIT_OK
    assert out == "The answer.\n", "no trace text may reach stdout"
    assert api.sent["intelligence_trace"] is True
    assert "  ✓ Understanding Request — Multi-part request  1.2s" in err
    # A step that finished after the answer started is held and printed after it,
    # set off by a blank line, and never twice.
    assert "\n\n  ✓ Final Synthesis — Findings combined  8.1s" in err
    assert err.count("Final Synthesis") == 1
    assert err.count("Understanding Request") == 1
    assert "Route: 2-model verification · 2 perspectives · no live data needed" in err
    assert "· A second perspective adds confidence." in err


def test_a_cut_off_answer_says_so(api, capsys):
    api.body = _answer("Partial", finish_reason="length")
    code, out, err = ask(capsys, "hi", "--max-tokens", "5")
    assert code == cli.EXIT_OK
    assert out == "Partial\n"
    assert "cut off" in err and "--max-tokens" in err


# --- guardrails ---------------------------------------------------------------

def test_there_is_no_way_to_pick_a_model(api, capsys):
    """The IP boundary: a caller chooses outcomes, never models or providers."""
    for flag in ("--model", "--provider", "--mode", "--panel"):
        code, _, _ = ask(capsys, "hi", flag, "x")
        assert code == cli.EXIT_USAGE, flag
    assert not api.requests
    help_text = cli._parser().format_help()
    for flag in ("--model", "--provider", "--mode"):
        assert flag not in help_text


def test_a_missing_key_fails_before_any_request(api, capsys, monkeypatch):
    monkeypatch.delenv("AIVANA_API_KEY")
    code, _, err = ask(capsys, "hi")
    assert code == cli.EXIT_AUTH
    assert "AI Studio" in err
    assert not api.requests


def test_the_key_never_reaches_the_terminal(api, capsys):
    api.status, api.body = 401, _error_body("invalid_api_key")
    _, out, err = ask(capsys, "hi")
    assert KEY not in out + err


def test_plain_http_to_a_remote_host_warns(api, capsys, monkeypatch):
    monkeypatch.setenv("AIVANA_API_BASE", "http://staging.example.com")
    _, _, err = ask(capsys, "hi")
    assert "unencrypted" in err
    assert api.requests[-1].url.host == "staging.example.com"


def test_plain_http_to_localhost_is_normal_local_development(api, capsys, monkeypatch):
    monkeypatch.setenv("AIVANA_API_BASE", "http://localhost:8088")
    _, _, err = ask(capsys, "hi")
    assert err == ""


def test_abbreviated_options_are_refused(api, capsys):
    """`--temp` must not mean --temperature: it would break the day --template ships."""
    code, _, _ = ask(capsys, "hi", "--temp", "0.5")
    assert code == cli.EXIT_USAGE
    assert not api.requests


def test_reserved_words_do_not_quietly_become_questions(api, capsys):
    code, _, err = ask(capsys, "chat", "about", "databases")
    assert code == cli.EXIT_USAGE
    assert "aivana ask chat about databases" in err
    assert not api.requests


def test_explicit_ask_is_the_way_around_a_reserved_word(api, capsys):
    code, _, _ = ask(capsys, "ask", "chat", "about", "databases")
    assert code == cli.EXIT_OK
    assert api.sent["prompt"] == "chat about databases"


# --- usage errors -------------------------------------------------------------

def test_no_question_is_a_usage_error(api, capsys):
    code, _, err = ask(capsys, "--effort", "low")
    assert code == cli.EXIT_USAGE
    assert "no question given" in err
    assert not api.requests


def test_the_bare_command_prints_help(api, capsys):
    code, out, _ = ask(capsys)
    assert code == cli.EXIT_USAGE
    assert "AIVANA_API_KEY" in out and "exit codes" in out
    assert not api.requests


def test_a_non_image_attachment_is_refused_locally(api, capsys, tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    code, _, err = ask(capsys, "Summarize", "--image", str(pdf))
    assert code == cli.EXIT_USAGE
    assert "pdftotext" in err
    assert not api.requests


def test_a_missing_image_file_is_named(api, capsys, tmp_path):
    code, _, err = ask(capsys, "hi", "--image", str(tmp_path / "nope.png"))
    assert code == cli.EXIT_USAGE
    assert "nope.png" in err
    assert not api.requests


def test_binary_piped_input_is_refused(api, capsys, monkeypatch):
    class BinaryStdin(Stdin):
        def read(self, *_):
            raise UnicodeDecodeError("utf-8", b"\x89", 0, 1, "invalid start byte")

    monkeypatch.setattr(sys, "stdin", BinaryStdin(tty=False))
    code, _, err = ask(capsys, "What is this?")
    assert code == cli.EXIT_USAGE
    assert "isn't text" in err
    assert not api.requests


def test_version(capsys):
    code = cli.main(["--version"])
    assert code == cli.EXIT_OK
    assert capsys.readouterr().out.startswith("aivana ")


# --- failures and exit codes ----------------------------------------------------

@pytest.mark.parametrize("status,code,exit_code", [
    (401, "invalid_api_key", cli.EXIT_AUTH),
    (401, "auth", cli.EXIT_AUTH),
    (403, "forbidden", cli.EXIT_AUTH),
    (403, "host_not_allowed", cli.EXIT_FAILED),
    (429, "rate_limit_exceeded", cli.EXIT_RATE_LIMITED),
    (402, "insufficient_credit", cli.EXIT_NO_CREDIT),
    (502, "upstream", cli.EXIT_TEMPORARY),
    (504, "timeout", cli.EXIT_TEMPORARY),
    (503, "config_unavailable", cli.EXIT_TEMPORARY),
    (500, "internal_error", cli.EXIT_FAILED),
])
@pytest.mark.parametrize("mode", [[], ["--json"]], ids=["stream", "json"])
def test_http_errors_map_to_exit_codes(api, capsys, status, code, exit_code, mode):
    api.status, api.body = status, _error_body(code)
    got, out, err = ask(capsys, "hi", *mode)
    assert got == exit_code
    assert out == ""
    assert "aivana: error: The server said no. (request id: req_123)" in err


def test_validation_errors_name_the_flag_to_fix(api, capsys):
    api.status = 422
    api.body = _error_body("invalid_request", "Request validation failed.", details=[
        {"loc": ["body", "temperature"], "msg": "Input should be less than or equal to 2",
         "type": "less_than_equal"}])
    code, _, err = ask(capsys, "hi", "--temperature", "3")
    assert code == cli.EXIT_FAILED
    assert "--temperature: Input should be less than or equal to 2" in err


def test_an_error_frame_inside_the_stream(api, capsys):
    api.body = _sse(STAGES[0],
                    ("error", {"type": "upstream_error", "message": "engine error"}),
                    ("done", {"finish_reason": "error", "usage": {}}))
    code, out, err = ask(capsys, "hi")
    assert code == cli.EXIT_TEMPORARY
    assert out == ""
    assert "safe to retry" in err
    assert "engine" not in err, "the CLI speaks for itself, not in the server's words"


def test_an_error_frame_after_part_of_the_answer_says_it_is_partial(api, capsys):
    api.body = _sse(*STAGES, ("delta", {"text": "Half an ans"}),
                    ("error", {"type": "upstream", "message": "Upstream provider error."}),
                    ("done", {"finish_reason": "error", "usage": {}}))
    code, out, err = ask(capsys, "hi")
    assert code == cli.EXIT_TEMPORARY
    assert out == "Half an ans\n"
    assert "incomplete" in err


def test_an_unreachable_api_is_temporary(api, capsys):
    api.raises = httpx.ConnectError("connection refused")
    code, _, err = ask(capsys, "hi")
    assert code == cli.EXIT_TEMPORARY
    assert "couldn't reach https://developers.aivana.ai" in err


def test_a_timeout_is_temporary(api, capsys):
    api.raises = httpx.ReadTimeout("too slow")
    code, _, err = ask(capsys, "hi")
    assert code == cli.EXIT_TEMPORARY
    assert "timed out" in err


def test_a_connection_dropped_mid_answer_is_flagged(api, capsys):
    def body():
        yield _sse(*STAGES, ("delta", {"text": "Half an ans"}))
        raise httpx.ReadError("connection reset")

    api.body = body
    code, out, err = ask(capsys, "hi")
    assert code == cli.EXIT_TEMPORARY
    assert out == "Half an ans\n"
    assert "incomplete" in err


def test_ctrl_c_exits_130(api, capsys):
    api.raises = KeyboardInterrupt()
    assert cli.main(["hi"]) == cli.EXIT_INTERRUPTED


def test_a_reader_closing_the_pipe_ends_quietly(api, capsys, monkeypatch):
    """`aivana ... | head -3`: the reader leaving early is not a crash."""
    class ClosedPipe(io.StringIO):
        def write(self, _):
            raise BrokenPipeError

    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    assert cli.main(["hi"]) == cli.EXIT_FAILED
