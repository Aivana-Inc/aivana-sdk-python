#!/usr/bin/env python3
"""Production smoke test for the `aivana` Python SDK: the first things a developer does, done against the real API
with the package exactly as a developer would install it.

    AIVANA_API_KEY=ai_live_... python smoke/smoke.py            the real run: three tiny billed calls
    AIVANA_API_KEY=ai_live_... python smoke/smoke.py --dry-run  checks the setup, calls nothing, spends nothing

What it checks, in order:
  1. the installed SDK is the version the release says it is (when EXPECTED_SDK_VERSION is set)
  2. a made-up key is refused with an AuthError                                  (free)
  3. the real key is accepted, and a bad request is a typed InvalidRequestError
     with a request id. The SDK has no read-only call, so this uses a request the API refuses at validation, after
     it has checked the key: an AuthError here would mean the key was refused     (free: refused before any work)
  4. one tiny generation                                                          (billed, call 1 of 3)
  5. one tiny streamed generation                                                 (billed, call 2 of 3)
  6. one async request cancelled while in flight                                  (may be billed, call 3 of 3)
     This check only BLOCKS when cancelling visibly failed. If the request finished before it could be cancelled
     (an unusually quick answer), nothing was learned, so it is reported as "not tested" and does not fail the
     run: a healthy release is never held up because production answered fast. See judge_cancel().

What it deliberately does NOT do: provoke a rate limit (the API's counters are per server task, so it would be flaky
and would put blocked requests in the production logs), retry-on-429 behaviour (proved offline in tests/test_retry.py),
or timeouts (a timed-out call can still be billed).

Safe by construction:
  - at most MAX_PAID_CALLS billed calls, counted in one place; a fourth is refused by this script
  - every line it prints passes through redact(), so the key never reaches a log
  - the key is only ever sent to https hosts (or to localhost, for the offline test)
  - it asserts the SHAPE of answers (non-empty, counts above zero, ids present), never their wording

Exit code: 0 no check failed (a check that could not be tried is "not tested", not a failure), 1 a check failed,
2 the setup is wrong (nothing was called).
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from urllib.parse import urlparse

import aivana
from aivana import AivanaError, AuthError, InvalidRequestError

MAX_PAID_CALLS = 3
PROMPT = "Reply with the single word: ready."
# Small on purpose. effort "low" and web search off keep the run short and the bill to a few cents.
TINY = {"max_tokens": 300, "effort": "low", "web_search": False}
API_DEFAULT = "https://api.aivana.ai"
# Long enough that the request is really in flight (a real answer takes seconds), short enough to be quick.
CANCEL_AFTER_S = 0.25

API_KEY = os.environ.get("AIVANA_API_KEY", "")
DRY_RUN = "--dry-run" in sys.argv


def redact(text, key=None):
    """Anything that looks like a key is hidden, and so is the exact key in use, whatever it looks like."""
    key = API_KEY if key is None else key
    s = str(text)
    if key:
        s = s.replace(key, "***")
    return re.sub(r"\bai_(?:live|test)_[A-Za-z0-9_-]+", "ai_***", s)


def out(line=""):
    sys.stdout.write(redact(line) + "\n")
    sys.stdout.flush()


def refuse_setup(message):
    out(f"SETUP PROBLEM: {message}")
    out("Nothing was called.")
    sys.exit(2)


def check_setup():
    if not API_KEY:
        refuse_setup("AIVANA_API_KEY is not set.")
    base = os.environ.get("AIVANA_API_BASE") or API_DEFAULT
    url = urlparse(base)
    local = url.hostname in ("127.0.0.1", "localhost")
    if not url.hostname or (url.scheme != "https" and not (local and url.scheme == "http")):
        refuse_setup("AIVANA_API_BASE must be an https address (the key is sent there).")
    return base.rstrip("/")


_paid_calls = 0


def spend_one(what):
    global _paid_calls
    if _paid_calls >= MAX_PAID_CALLS:
        raise RuntimeError(f"refusing a billed call ({what}): the cap is {MAX_PAID_CALLS} per run")
    _paid_calls += 1


def describe(err):
    if isinstance(err, AivanaError):
        bits = [type(err).__name__, f"code {err.code}"]
        if err.request_id:
            bits.append(f"request {err.request_id}")
        text = ", ".join(bits) + f" - {str(err.message)[:160]}"
        # The gate is permanent, so an empty test account must read as "fund it", not as an SDK problem.
        if err.code == "insufficient_credit":
            text += ('  >> THE TEST ACCOUNT IS OUT OF CREDIT: fund it (smoke/README.md, "Keeping it funded"); '
                     "this is not an SDK fault")
        return text
    return f"{type(err).__name__} - {str(err)[:160]}"


class Inconclusive(Exception):
    """A check that could not be tried (the request finished before it could be cancelled): not a failure, not a pass."""


results = []


def check(name, fn):
    try:
        note = fn()
        if asyncio.iscoroutine(note):
            note = asyncio.run(note)
        results.append({"name": name, "status": "pass", "note": note or ""})
        out(f"PASS  {name}" + (f"  ({note})" if note else ""))
        return True
    except Inconclusive as err:
        results.append({"name": name, "status": "inconclusive", "note": str(err)})
        out(f"NOT TESTED  {name}")
        out(f"      {err}")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            out(f"::warning title=Smoke test: {name}::not tested this run: {err}")
        return True
    except BaseException as err:  # noqa: BLE001 - a smoke test reports everything, including a stray cancel
        if isinstance(err, (KeyboardInterrupt, SystemExit)):
            raise
        results.append({"name": name, "status": "fail", "note": describe(err)})
        out(f"FAIL  {name}")
        out(f"      {describe(err)}")
        return False


def judge_cancel(*, cancel_requested, outcome, err=None, took_s=0.0, limit_s=5.0):
    """Judges the cancel check from what happened, so the rule is one place that can be tested without a network.

    cancel_requested       what Task.cancel() returned: False means the request had already finished (answer or
                           error) when the cancel was due, so it was not in flight
    outcome                "cancelled" | "resolved" | "rejected", after the cancel was requested
    Only a request that was demonstrably in flight when it was cancelled can fail the check.
    """
    if not cancel_requested:
        return "inconclusive", "the request finished before it could be cancelled, so cancelling was not tested this run"
    if outcome == "cancelled":
        if took_s >= limit_s:
            return "fail", f"cancelling took {took_s:.1f} s to take effect"
        return "pass", f"stopped after {took_s * 1000:.0f} ms"
    # asyncio delivers a cancel into the coroutine even if the awaited reply has just arrived, so a request that was
    # in flight and ends any other way did not honour the cancel
    ended = "an answer" if outcome == "resolved" else describe(err)
    return "fail", f"the request was in flight when it was cancelled, but it ended with {ended} instead of being cancelled"


def expect(condition, message):
    if not condition:
        raise AssertionError(message)


def positive_int(n):
    return isinstance(n, int) and not isinstance(n, bool) and n > 0


def finish(code):
    passed = sum(1 for r in results if r["status"] == "pass")
    untested = sum(1 for r in results if r["status"] == "inconclusive")
    note = f", {untested} not tested this run" if untested else ""
    out(f"\n{passed} of {len(results)} checks passed{note}; {_paid_calls} billed call(s) made.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        label = {"pass": "pass", "fail": "FAIL", "inconclusive": "not tested"}
        rows = [f"| {label[r['status']]} | {r['name']} | {redact(r['note']).replace('|', '/')} |" for r in results]
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("### aivana (Python) production smoke test\n\n| | check | detail |\n|---|---|---|\n"
                     + "\n".join(rows) + f"\n\n{passed} of {len(results)} passed{note}; {_paid_calls} billed call(s).\n")
    return code


def main():
    base = check_setup()
    version = getattr(aivana, "__version__", "unknown")
    out(f"aivana {version}  ->  {base}" + ("  (dry run: nothing will be called)" if DRY_RUN else ""))

    if DRY_RUN:
        out(f"Plan: 2 free checks, then up to {MAX_PAID_CALLS} tiny billed calls "
            f"(max_tokens {TINY['max_tokens']}, effort {TINY['effort']}, web search off).")
        out("Nothing was called.")
        return 0

    aivana.set_api_base(base)
    # retries off: a smoke test must report what the API did on the first try, not hide a 429 behind a retry.
    aivana.set_max_retries(0)

    def sdk_version():
        want = os.environ.get("EXPECTED_SDK_VERSION")
        if not want:
            return f"version {version}; EXPECTED_SDK_VERSION not set, so not compared"
        expect(version == want, f"installed {version}, expected {want}")
        return f"version {version}"

    check("the installed SDK is the release being tested", sdk_version)

    def made_up_key():
        aivana.set_api_key("ai_live_" + "x" * 32)
        try:
            aivana.generate(PROMPT, timeout=30)
        except AuthError:
            return "refused"
        except Exception as err:  # noqa: BLE001
            raise AssertionError(f"expected AuthError, got {describe(err)}") from err
        finally:
            aivana.set_api_key(API_KEY)
        raise AssertionError("a made-up key was accepted")

    check("a made-up key is refused with AuthError", made_up_key)

    def real_key_and_bad_request():
        aivana.set_api_key(API_KEY)
        try:
            # refused by validation after the key is checked, before any work: free
            aivana.generate(PROMPT, effort="not-a-real-effort", timeout=30)
        except AuthError as err:
            raise AssertionError("the real key was refused (AuthError)") from err
        except InvalidRequestError as err:
            expect(err.code == "invalid_request", f"expected code invalid_request, got {err.code}")
            expect(isinstance(err.request_id, str) and len(err.request_id) > 0, "the error carried no request_id")
            return "key accepted; request refused as invalid"
        except Exception as err:  # noqa: BLE001
            raise AssertionError(f"expected InvalidRequestError, got {describe(err)}") from err
        raise AssertionError("a bad request was accepted")

    if not check("the real key is accepted, and a bad request is a typed InvalidRequestError",
                 real_key_and_bad_request):
        out("Stopping: without a working key the remaining checks cannot say anything useful.")
        return finish(1)

    def generation():
        spend_one("generate")
        r = aivana.generate(PROMPT, timeout=90, **TINY)
        expect(isinstance(r.answer, str) and r.answer.strip(), f"the answer was empty (finish_reason {r.finish_reason})")
        expect(isinstance(r.request_id, str) and r.request_id, "no request_id")
        expect(positive_int(r.usage.input_tokens), "usage.input_tokens is not a positive whole number")
        expect(positive_int(r.usage.output_tokens), "usage.output_tokens is not a positive whole number")
        expect(isinstance(r.usage.credits, (int, float)) and r.usage.credits >= 0, "usage.credits is not a number")
        expect(len(r.models_used) > 0, "models_used is empty")
        expect(r.finish_reason in ("stop", "length"), f"unexpected finish_reason {r.finish_reason}")
        expect(isinstance(r.notices, list), "notices is not a list")
        return (f"{r.usage.input_tokens} in / {r.usage.output_tokens} out, {r.latency_ms} ms, "
                f"request {r.request_id}")

    check("one tiny generation", generation)

    def streaming():
        spend_one("generate(stream=True)")
        deltas, text, done, errors = 0, "", None, 0
        for chunk in aivana.generate(PROMPT, stream=True, timeout=90, **TINY):
            if chunk.event == "delta":
                deltas += 1
                text += chunk.delta
            elif chunk.event == "done":
                done = chunk.data
            elif chunk.event == "error":
                errors += 1
        expect(errors == 0, f"the stream carried {errors} error event(s)")
        expect(deltas > 0 and text.strip(), "the stream carried no answer text")
        expect(done is not None, "the stream never sent its done event")
        expect(done.get("finish_reason") != "error", "the stream ended with finish_reason error")
        usage = done.get("usage") or {}
        expect(positive_int(usage.get("input_tokens")) and positive_int(usage.get("output_tokens")),
               "the done event's token counts are not positive whole numbers")
        expect(isinstance(done.get("request_id"), str) and done["request_id"], "the done event had no request_id")
        return (f"{deltas} pieces, {usage['input_tokens']} in / {usage['output_tokens']} out, "
                f"request {done['request_id']}")

    check("one tiny streamed generation", streaming)

    async def cancelled():
        spend_one("generate_async cancelled")
        task = asyncio.ensure_future(aivana.generate_async(PROMPT, timeout=90, **TINY))
        await asyncio.sleep(CANCEL_AFTER_S)
        # In flight means: still pending when the cancel is sent. Task.cancel() says so exactly: it returns False
        # for a task that has already finished, so nothing is guessed from a clock.
        cancel_requested = task.cancel()
        cancelled_at = time.monotonic()
        outcome, err = "resolved", None
        try:
            await task
        except asyncio.CancelledError:
            outcome = "cancelled"
        except Exception as exc:  # noqa: BLE001
            outcome, err = "rejected", exc
        status, note = judge_cancel(cancel_requested=cancel_requested, outcome=outcome, err=err,
                                    took_s=time.monotonic() - cancelled_at)
        if status == "fail":
            raise AssertionError(note)
        if status == "inconclusive":
            raise Inconclusive(note)
        return note

    check("an async request cancelled while in flight stops promptly", cancelled)

    return finish(1 if any(r["status"] == "fail" for r in results) else 0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as err:  # noqa: BLE001
        out(f"FAIL  the smoke test itself broke: {describe(err)}")
        sys.exit(1)
