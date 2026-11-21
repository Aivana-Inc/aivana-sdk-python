"""The production smoke test (smoke/smoke.py), run against a local stand-in for the API.

A smoke test that has only ever passed proves nothing, so most of these cases make the stand-in misbehave in one way
(a made-up key accepted, an empty answer, an error inside the stream...) and check the script says FAIL.
Nothing here touches the network beyond 127.0.0.1 and nothing needs a key.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "smoke" / "smoke.py"
GOOD_KEY = "ai_test_" + "g" * 32
VERSION = importlib.metadata.version("aivana")


def _load_script():
    spec = importlib.util.spec_from_file_location("aivana_smoke_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _envelope(code, message, status):
    return status, {"error": {"type": code, "code": code, "message": message, "request_id": "req_stub"}}


@contextmanager
def stub(quirk=None):
    """A stand-in for the few routes the script uses. `quirk` makes it misbehave in one named way."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, obj, headers=None):
            raw = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            key = self.headers.get("X-API-Key")
            seen.append({"path": self.path, "key": key, "body": body})
            key_ok = True if quirk == "accepts-any-key" else key == GOOD_KEY
            if not key_ok or (quirk == "refuses-real-key" and key == GOOD_KEY):
                # the message echoes the key on purpose: the script must not print it
                return self._send(*_envelope("auth", f"Invalid API key {key}", 401))
            if quirk == "rate-limited" and key == GOOD_KEY:
                status, payload = _envelope("rate_limit_exceeded", "Too many requests", 429)
                return self._send(status, payload, {"Retry-After": "0"})
            # What the real API does (intelligence_engine/api/envelopes.py): temperature must be 0..2, so 5 is a 422
            # before any work; an unknown `effort` is NOT an error (it is quietly treated as "auto"), so it is accepted.
            temp = body.get("temperature")
            if (quirk != "accepts-bad-requests" and isinstance(temp, (int, float)) and (temp > 2 or temp < 0)):
                return self._send(*_envelope("invalid_request", "The request body or query is not valid.", 422))
            if quirk == "no-credit" and body.get("effort") == "low":
                return self._send(*_envelope("insufficient_credit", "Your balance is empty.", 402))
            if quirk == "fails-fast" and self.path == "/v1/generate" and body.get("effort") == "low":
                return self._send(*_envelope("internal_error", "boom", 500))
            delay = 0 if quirk == "answers-instantly" else 0.6
            if self.path == "/v1/generate":
                time.sleep(delay)
                try:
                    return self._send(200, {
                        "id": "gen_1", "request_id": "" if quirk == "no-request-id" else "req_ok",
                        "answer": "   " if quirk == "empty-answer" else "ready",
                        "intent": {"name": "chat", "confidence": 1.0}, "models_used": ["aivana-mmi"],
                        "usage": {"input_tokens": 12, "output_tokens": 0 if quirk == "zero-tokens" else 3,
                                  "credits": 0.001},
                        "latency_ms": 800, "finish_reason": "stop", "notices": [],
                    })
                except (BrokenPipeError, ConnectionResetError):
                    return
            if self.path == "/v1/generate:stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()

                def ev(event, data):
                    self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())

                ev("delta", {"text": "rea"})
                if quirk == "stream-error":
                    ev("error", {"message": "upstream failed"})
                elif quirk == "stream-error-then-clean-done":
                    ev("error", {"message": "upstream hiccup"})
                    ev("delta", {"text": "dy"})
                else:
                    ev("delta", {"text": "dy"})
                if quirk != "stream-no-done":
                    ev("done", {"finish_reason": "error" if quirk == "stream-error" else "stop",
                                "request_id": "req_stream",
                                "usage": {"input_tokens": 12, "output_tokens": 3, "cached_tokens": 0, "credits": 0.001}})
                return
            self._send(404, {"error": {"code": "not_found", "message": "no", "request_id": "r"}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", seen
    finally:
        server.shutdown()
        server.server_close()


def run_script(env, *args):
    base_env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT),
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    r = subprocess.run([sys.executable, str(SCRIPT), *args], env={**base_env, **env}, capture_output=True,
                       text=True, timeout=90)
    return r.returncode, r.stdout, r.stderr


def billed(seen):
    gen = [r for r in seen if r["path"] == "/v1/generate" and r["body"].get("effort") == "low"]
    stream = [r for r in seen if r["path"] == "/v1/generate:stream"]
    return gen, stream


def test_every_check_passes_against_a_well_behaved_api_with_exactly_three_billed_calls():
    with stub() as (base, seen):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base,
                                   "EXPECTED_SDK_VERSION": VERSION})
        assert code == 0, out
        assert "6 of 6 checks passed; 3 billed call(s) made" in out
        gen, stream = billed(seen)
        assert len(gen) + len(stream) == _load_script().MAX_PAID_CALLS


def test_the_billed_calls_are_tiny_and_never_search_the_web():
    with stub() as (base, seen):
        run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        gen, stream = billed(seen)
        assert len(gen) + len(stream) == 3
        for b in gen + stream:
            assert b["body"]["max_tokens"] == 300
            assert b["body"]["web_search"] is False
            assert b["body"]["effort"] == "low"
            assert len(b["body"]["prompt"]) < 60


def test_sdk_retries_are_off_so_a_429_is_reported_on_the_first_try():
    with stub("rate-limited") as (base, seen):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1
        # one request with the real key: with the SDK's default of two retries there would be three
        assert len([r for r in seen if r["key"] == GOOD_KEY]) == 1
        assert "RateLimitError" in out


def test_a_dry_run_checks_the_setup_and_calls_nothing():
    with stub() as (base, seen):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base}, "--dry-run")
        assert code == 0
        assert "Nothing was called" in out
        assert seen == []


def test_no_key_is_a_setup_problem_and_nothing_is_called():
    with stub() as (base, seen):
        code, out, _ = run_script({"AIVANA_API_BASE": base})
        assert code == 2
        assert "AIVANA_API_KEY is not set" in out
        assert seen == []


def test_the_key_is_never_sent_to_a_plain_http_host_that_is_not_this_machine():
    code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": "http://example.org"})
    assert code == 2
    assert "must be an https address" in out
    assert GOOD_KEY not in out


def test_the_key_never_appears_in_the_output_even_when_the_api_echoes_it_back_in_an_error():
    with stub("refuses-real-key") as (base, _):
        code, out, err = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert GOOD_KEY not in out and GOOD_KEY not in err
        assert "g" * 32 not in out


def test_redact_hides_the_exact_key_and_anything_shaped_like_one():
    smoke = _load_script()
    assert smoke.redact("key is SECRETVALUE here", "SECRETVALUE") == "key is *** here"
    assert smoke.redact("saw ai_live_AbC123xyz and ai_test_Zzz", "") == "saw ai_*** and ai_***"
    assert smoke.redact("nothing to hide", "") == "nothing to hide"


def test_a_made_up_key_that_is_accepted_fails_the_run():
    with stub("accepts-any-key") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1
        assert "FAIL  a made-up key is refused with AuthError" in out


def test_a_real_key_that_is_refused_stops_the_run_before_any_billed_call():
    with stub("refuses-real-key") as (base, seen):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1
        assert "Stopping: without a working key" in out
        gen, stream = billed(seen)
        assert len(gen) + len(stream) == 0


def test_a_bad_request_that_the_api_accepts_fails_the_run():
    with stub("accepts-bad-requests") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1
        assert "FAIL  the real key is accepted, and a bad request is a typed InvalidRequestError" in out


def test_an_empty_answer_fails_the_generation_check():
    with stub("empty-answer") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1
        assert "FAIL  one tiny generation" in out and "the answer was empty" in out


def test_zero_token_counts_fail_the_generation_check():
    with stub("zero-tokens") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1
        assert "output_tokens is not a positive whole number" in out


def test_a_response_with_no_request_id_fails_the_generation_check():
    with stub("no-request-id") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1
        assert "no request_id" in out


def test_an_error_event_inside_the_stream_fails_the_streaming_check():
    with stub("stream-error") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1
        assert "FAIL  one tiny streamed generation" in out


def test_an_error_event_inside_an_otherwise_normal_looking_stream_still_fails():
    with stub("stream-error-then-clean-done") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1
        assert "the stream carried 1 error event" in out


def test_a_stream_that_never_sends_done_fails_the_streaming_check():
    with stub("stream-no-done") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1
        assert "never sent its done event" in out


def test_a_release_whose_installed_version_is_not_the_expected_one_fails():
    with stub() as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base,
                                   "EXPECTED_SDK_VERSION": "0.0.1"})
        assert code == 1
        assert "expected 0.0.1" in out


def test_the_billed_call_cap_is_three_and_a_fourth_billed_call_is_refused_by_the_script_itself():
    smoke = _load_script()
    assert smoke.MAX_PAID_CALLS == 3
    for what in ("one", "two", "three"):
        smoke.spend_one(what)
    with pytest.raises(RuntimeError, match="the cap is 3 per run"):
        smoke.spend_one("four")


def test_an_answer_that_arrives_before_the_cancel_is_not_tested_not_a_failure():
    """A healthy release is never held up by a fast API."""
    with stub("answers-instantly") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 0, out
        assert "NOT TESTED  an async request cancelled while in flight" in out
        assert "6 of 6 checks passed" not in out
        assert "5 of 6 checks passed, 1 not tested this run; 3 billed call(s) made" in out
        assert "FAIL" not in out


def test_a_not_tested_cancel_is_a_warning_annotation_in_github_and_silent_elsewhere():
    with stub("answers-instantly") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base, "GITHUB_ACTIONS": "true"})
        assert code == 0
        assert "::warning title=Smoke test: an async request cancelled while in flight stops promptly::not tested this run" in out
        _, quiet, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert "::warning" not in quiet


def test_an_api_fault_that_ends_the_request_before_the_cancel_is_not_blamed_on_cancelling():
    with stub("fails-fast") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1  # the generation check fails on the 500, which is the real problem
        assert "FAIL  one tiny generation" in out
        assert "NOT TESTED  an async request cancelled" in out
        assert "FAIL  an async request cancelled" not in out


def test_an_empty_test_account_reads_as_fund_it_not_an_sdk_fault_and_still_stops_the_release():
    with stub("no-credit") as (base, _):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 1
        assert "THE TEST ACCOUNT IS OUT OF CREDIT: fund it" in out
        assert "not an SDK fault" in out


# judge_cancel: the rule for the cancel check, with no network and no timing
def _judge(**kw):
    base = dict(cancel_requested=True, outcome="cancelled", err=None, took_s=0.003)
    return _load_script().judge_cancel(**{**base, **kw})[0]


def test_judge_cancel_a_request_in_flight_that_is_cancelled_promptly_passes():
    assert _judge() == "pass"


def test_judge_cancel_a_request_that_had_already_finished_is_inconclusive_never_a_failure():
    assert _judge(cancel_requested=False, outcome="resolved") == "inconclusive"
    assert _judge(cancel_requested=False, outcome="rejected", err=RuntimeError("x")) == "inconclusive"


def test_judge_cancel_in_flight_and_cancelled_but_it_ends_any_other_way_is_a_failure():
    assert _judge(outcome="resolved") == "fail"
    assert _judge(outcome="rejected", err=RuntimeError("boom")) == "fail"


def test_judge_cancel_in_flight_but_slow_to_take_effect_is_a_failure_with_the_limit_given():
    assert _judge(took_s=5.0) == "fail"
    assert _judge(took_s=4.99) == "pass"


def test_the_bad_request_check_uses_an_out_of_range_temperature_never_an_unknown_effort():
    """The real API refuses temperature 5 but quietly accepts an unknown effort (it treats it as auto)."""
    with stub() as (base, seen):
        code, out, _ = run_script({"AIVANA_API_KEY": GOOD_KEY, "AIVANA_API_BASE": base})
        assert code == 0, out
        bad = [r for r in seen if r["body"].get("temperature") == 5]
        assert len(bad) == 1
        assert "effort" not in bad[0]["body"], "the invalid request must not rely on effort"
        import httpx
        res = httpx.post(base + "/v1/generate", headers={"X-API-Key": GOOD_KEY},
                         json={"prompt": "x", "effort": "not-a-real-effort"})
        assert res.status_code == 200
