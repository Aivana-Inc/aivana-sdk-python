"""Retries and Retry-After.

Only a per-minute rate limit is retried, because the API refuses it before doing any work, so
asking again cannot bill twice. Everything else that can go wrong, a quota, a timeout, a 5xx, a
dropped connection, may have been billed and must reach the caller untouched. Most of this file
is that second half: it is what keeps a retry from costing a customer money. Mirrors
@aivana/sdk's test/retry.test.mjs.

    python3 -m pytest tests/ -q
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aivana  # noqa: E402
from aivana import client as sdk  # noqa: E402
from aivana.exceptions import parse_retry_after  # noqa: E402

OK = {"id": "gen_1", "answer": "hello", "intent": {"name": "direct_chat", "confidence": 0.0}}


def limited(headers=None, code="rate_limit_exceeded", **extra):
    return httpx.Response(429, headers=headers or {}, json={"error": {
        "type": code, "code": code, "message": "Too many requests from this IP.",
        "request_id": "r1", **extra}})


def good():
    return httpx.Response(200, json=OK)


def sse_ok():
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          content=b'event: done\ndata: {"ok": true}\n\n')


@pytest.fixture
def api(monkeypatch):
    """Scripted answers, one per request; every request and every wait is recorded, none is taken."""
    state = {"calls": [], "waits": [], "script": [good()]}

    def handler(request):
        state["calls"].append(request)
        script = state["script"]
        item = script[min(len(state["calls"]) - 1, len(script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    real, real_async = httpx.Client, httpx.AsyncClient
    monkeypatch.setattr(sdk.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(sdk.httpx, "AsyncClient",
                        lambda **kw: real_async(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(sdk, "_sleep", lambda s: state["waits"].append(s))

    async def asleep(s):
        state["waits"].append(s)

    monkeypatch.setattr(sdk, "_asleep", asleep)
    monkeypatch.setattr(sdk, "api_key", "ai_live_test")
    monkeypatch.setattr(sdk, "max_retries", 2)
    monkeypatch.setattr(sdk, "max_retry_wait", 30.0)

    class Api:
        calls, waits = state["calls"], state["waits"]

        def script(self, *items):
            state["script"] = list(items)

    return Api()


# --- reading Retry-After -------------------------------------------------------

def test_a_rate_limit_error_carries_the_seconds_the_api_said_to_wait(api):
    api.script(limited({"Retry-After": "7"}))
    with pytest.raises(aivana.RateLimitError) as e:
        aivana.generate("hi", max_retries=0)
    assert e.value.retry_after == 7


def test_retry_after_as_an_http_date_becomes_seconds_from_now():
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:20 GMT", now=1792567680.0 - 0) is not None
    import email.utils
    import time
    at = email.utils.formatdate(time.time() + 20, usegmt=True)
    assert 17 < parse_retry_after(at) <= 20


@pytest.mark.parametrize("bad", ["", "soon", "-5", "NaN", None])
def test_a_retry_after_that_is_not_a_wait_is_none_never_a_wait(bad):
    assert parse_retry_after(bad) is None


def test_the_bodys_retry_after_ms_is_used_when_there_is_no_header(api):
    api.script(limited({}, retry_after_ms=2500))
    with pytest.raises(aivana.RateLimitError) as e:
        aivana.generate("hi", max_retries=0)
    assert e.value.retry_after == 2.5


def test_the_header_wins_over_the_body(api):
    api.script(limited({"Retry-After": "4"}, retry_after_ms=9000))
    with pytest.raises(aivana.RateLimitError) as e:
        aivana.generate("hi", max_retries=0)
    assert e.value.retry_after == 4


def test_no_header_and_no_body_is_none(api):
    api.script(limited())
    with pytest.raises(aivana.RateLimitError) as e:
        aivana.generate("hi", max_retries=0)
    assert e.value.retry_after is None


# --- retrying a per-minute rate limit -------------------------------------------

def test_a_rate_limit_is_retried_and_the_call_then_succeeds(api):
    api.script(limited({"Retry-After": "2"}), good())
    assert aivana.generate("hi").answer == "hello"
    assert len(api.calls) == 2 and len(api.waits) == 1


def test_the_wait_is_at_least_what_the_api_said_and_a_little_more(api):
    api.script(limited({"Retry-After": "2"}), good())
    aivana.generate("hi")
    assert 2.0 <= api.waits[0] <= 2.5  # jitter is at most a quarter, and never more than a second


def test_with_no_retry_after_the_wait_backs_off(api):
    api.script(limited(), limited(), good())
    aivana.generate("hi")
    assert len(api.waits) == 2
    assert 1.0 <= api.waits[0] <= 1.25 and 2.0 <= api.waits[1] <= 2.5


def test_every_attempt_sends_the_same_request_once_with_the_key(api):
    api.script(limited({"Retry-After": "0"}), limited({"Retry-After": "0"}), good())
    aivana.generate("same question", web_search=False)
    assert len(api.calls) == 3
    assert len({c.content for c in api.calls}) == 1
    assert all(c.headers["x-api-key"] == "ai_live_test" and c.method == "POST" for c in api.calls)


def test_it_gives_up_after_max_retries_and_raises_the_last_rate_limit_error(api):
    api.script(limited({"Retry-After": "0"}))
    with pytest.raises(aivana.RateLimitError):
        aivana.generate("hi")
    assert len(api.calls) == 3  # the first try and the default two retries


def test_max_retries_zero_asks_once(api):
    api.script(limited({"Retry-After": "0"}))
    with pytest.raises(aivana.RateLimitError):
        aivana.generate("hi", max_retries=0)
    assert len(api.calls) == 1


def test_a_calls_own_max_retries_overrides_the_modules_in_both_directions(api, monkeypatch):
    monkeypatch.setattr(sdk, "max_retries", 5)
    api.script(limited({"Retry-After": "0"}))
    with pytest.raises(aivana.RateLimitError):
        aivana.generate("hi", max_retries=1)
    assert len(api.calls) == 2
    api.calls.clear()
    monkeypatch.setattr(sdk, "max_retries", 0)
    api.script(limited({"Retry-After": "0"}), good())
    assert aivana.generate("hi", max_retries=3).answer == "hello"
    assert len(api.calls) == 2


def test_a_wait_longer_than_the_ceiling_is_not_taken_the_error_is_raised_at_once(api):
    api.script(limited({"Retry-After": "120"}), good())  # the default ceiling is 30 s
    with pytest.raises(aivana.RateLimitError) as e:
        aivana.generate("hi")
    assert e.value.retry_after == 120 and len(api.calls) == 1 and api.waits == []


def test_the_ceiling_is_the_callers_to_set(api):
    aivana.max_retry_wait = 60  # the same Stripe-style setting as aivana.api_key
    api.script(limited({"Retry-After": "40"}), good())
    assert aivana.generate("hi").answer == "hello"
    assert len(api.calls) == 2


def test_chat_turns_are_retried(api):
    api.script(limited({"Retry-After": "0"}), good())
    assert aivana.Chat().send("hi").answer == "hello"
    assert len(api.calls) == 2


def test_chat_takes_its_own_max_retries(api):
    api.script(limited({"Retry-After": "0"}))
    with pytest.raises(aivana.RateLimitError):
        aivana.Chat(max_retries=0).send("hi")
    assert len(api.calls) == 1


def test_a_refused_request_is_retried_before_streaming_starts(api):
    api.script(limited({"Retry-After": "0"}), sse_ok())
    chunks = list(aivana.generate("hi", stream=True))
    assert len(api.calls) == 2 and chunks


def test_async_generate_is_retried(api):
    api.script(limited({"Retry-After": "0"}), good())
    res = asyncio.run(aivana.generate_async("hi"))
    assert res.answer == "hello" and len(api.calls) == 2 and len(api.waits) == 1


def test_async_stream_is_retried_before_the_first_byte(api):
    api.script(limited({"Retry-After": "0"}), sse_ok())

    async def run():
        return [c async for c in aivana.generate_stream("hi")]

    assert asyncio.run(run()) and len(api.calls) == 2


def test_async_gives_up_after_max_retries(api):
    api.script(limited({"Retry-After": "0"}))
    with pytest.raises(aivana.RateLimitError):
        asyncio.run(aivana.generate_async("hi", max_retries=1))
    assert len(api.calls) == 2


# --- what is NEVER retried: a repeat of any of these could bill twice -----------

@pytest.mark.parametrize("code", ["token_quota", "monthly_quota", "spend_limit_reached", "slow_down",
                                  "credit_hold_busy"])
def test_a_429_that_is_not_a_per_minute_rate_limit_is_raised_not_retried(api, code):
    api.script(limited({"Retry-After": "0"}, code), good())
    with pytest.raises(aivana.RateLimitError) as e:
        aivana.generate("hi")
    assert e.value.code == code and len(api.calls) == 1


@pytest.mark.parametrize("status,code", [(500, "internal_error"), (502, "upstream"), (503, "internal_error"),
                                         (504, "internal_error")])
def test_a_5xx_is_never_retried_the_work_may_have_been_done_and_billed(api, status, code):
    api.script(httpx.Response(status, headers={"Retry-After": "0"},
                              json={"error": {"code": code, "message": "x"}}), good())
    with pytest.raises(aivana.AivanaError):
        aivana.generate("hi")
    assert len(api.calls) == 1


@pytest.mark.parametrize("status,code,cls", [(401, "auth", aivana.AuthError), (403, "forbidden", aivana.ForbiddenError),
                                             (400, "invalid_request", aivana.InvalidRequestError),
                                             (402, "insufficient_credit", aivana.AivanaError)])
def test_other_client_errors_are_never_retried(api, status, code, cls):
    api.script(httpx.Response(status, headers={"Retry-After": "0"},
                              json={"error": {"code": code, "message": "x"}}), good())
    with pytest.raises(cls):
        aivana.generate("hi")
    assert len(api.calls) == 1


def test_a_dropped_connection_is_never_retried(api):
    api.script(httpx.ConnectError("refused"), good())
    with pytest.raises(httpx.ConnectError):
        aivana.generate("hi")
    assert len(api.calls) == 1


def test_a_timeout_is_never_retried(api):
    api.script(httpx.ReadTimeout("timed out"), good())
    with pytest.raises(httpx.ReadTimeout):
        aivana.generate("hi")
    assert len(api.calls) == 1


def test_a_streaming_error_that_is_not_a_rate_limit_is_not_retried(api):
    api.script(httpx.Response(500, json={"error": {"code": "internal_error", "message": "x"}}), sse_ok())
    with pytest.raises(aivana.AivanaError):
        list(aivana.generate("hi", stream=True))
    assert len(api.calls) == 1


def test_only_a_rate_limit_has_retry_after(api):
    api.script(httpx.Response(401, headers={"Retry-After": "5"}, json={"error": {"code": "auth", "message": "no"}}))
    with pytest.raises(aivana.AuthError) as e:
        aivana.generate("hi")
    assert not hasattr(e.value, "retry_after")


# --- the settings -------------------------------------------------------------------

def test_the_defaults_are_two_retries_and_a_thirty_second_ceiling():
    assert sdk.max_retries == 2 and sdk.max_retry_wait == 30.0


@pytest.mark.parametrize("bad", [-1, 1.5, "2", None, True])
def test_a_max_retries_that_is_not_a_count_is_refused(bad, monkeypatch):
    monkeypatch.setattr(sdk, "max_retries", 2)
    with pytest.raises(aivana.InvalidRequestError):
        aivana.set_max_retries(bad)
    assert sdk.max_retries == 2


@pytest.mark.parametrize("bad", [-1, "x", float("nan"), float("inf"), None, True])
def test_a_max_retry_wait_that_is_not_a_wait_is_refused(bad, monkeypatch):
    monkeypatch.setattr(sdk, "max_retry_wait", 30.0)
    with pytest.raises(aivana.InvalidRequestError):
        aivana.set_max_retry_wait(bad)
    assert sdk.max_retry_wait == 30.0


def test_a_calls_bad_max_retries_is_refused_before_any_request(api):
    with pytest.raises(aivana.InvalidRequestError):
        aivana.generate("hi", max_retries=-2)
    assert api.calls == []


def test_max_retries_is_not_sent_to_the_api(api):
    aivana.generate("hi", max_retries=3)
    sent = json.loads(api.calls[0].content)
    assert "max_retries" not in sent and "maxRetries" not in sent


def test_the_settings_are_read_and_written_on_the_package_like_api_key(monkeypatch):
    monkeypatch.setattr(sdk, "max_retries", 2)
    monkeypatch.setattr(sdk, "max_retry_wait", 30.0)
    assert aivana.max_retries == 2 and aivana.max_retry_wait == 30.0
    aivana.max_retries = 4
    aivana.max_retry_wait = 12
    assert sdk.max_retries == 4 and sdk.max_retry_wait == 12.0  # the client reads its own, not a stale copy
    with pytest.raises(aivana.InvalidRequestError):
        aivana.max_retries = -1
    assert sdk.max_retries == 4
    assert {"max_retries", "max_retry_wait", "set_max_retries", "set_max_retry_wait"} <= set(aivana.__all__)
