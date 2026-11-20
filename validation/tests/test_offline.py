"""Offline validation of the aivana Python SDK (no key, no network, no credit).

HTTP is intercepted with respx, so these tests check what the SDK *sends* and how it
*interprets* responses. Response bodies mirror real ones captured from the dev API
(first_call_results.txt, Sept 29 2026) and the shapes on the Errors & Rate Limits page.

Tests marked xfail(strict=True) assert DOCUMENTED behaviour the SDK does not meet yet.
Each reason starts with a finding ID (F1, F2, ...) from the validation report.
"""
from __future__ import annotations

import asyncio
import json
import sys

import httpx
import pytest
import respx

import aivana
from aivana import (AivanaError, AuthError, Chat, ForbiddenError, GenerateResponse,
                    InvalidRequestError, RateLimitError, StreamChunk, UpstreamError)

from conftest import DOCUMENTED_DEFAULT_BASE, OFFLINE_BASE

case = pytest.mark.case

# A real 200 body from dev-developers.aivana.ai (first-call test, Sept 29).
REAL_OK = {
    "id": "gen_d609a1c17aad8a8cf6a5d2f5", "request_id": "req_79a1dfa9af6fd183c9869f1b",
    "answer": "Moon pulls silver tides  \nSalt wind braids the dusk with foam  \nDeep songs kiss the shore",
    "intent": {"name": "creative", "confidence": 0.0, "signal": ""},
    "structured": None, "structured_error": None, "models_used": ["aivana-mmi"],
    "usage": {"input_tokens": 7, "output_tokens": 23, "cached_tokens": 0, "credits": 0.000099},
    "latency_ms": 4628, "finish_reason": "stop", "notices": [], "pending_action": None, "trace": None,
}
# A real 401 body from developers.aivana.ai - note: no request_id in it.
REAL_401 = {"error": {"type": "auth", "code": "invalid_api_key",
                      "message": "Invalid or expired API key. Generate a new key or check its expiry."}}


def err(code, message="x", rid="req_test", **extra):
    return {"error": {"type": code, "code": code, "message": message, "request_id": rid, **extra}}


def sse(*events):
    out = ""
    for ev, data in events:
        out += f"event: {ev}\ndata: {json.dumps(data)}\n\n"
    return out


@pytest.fixture
def api(offline):
    with respx.mock(base_url=OFFLINE_BASE, assert_all_called=False) as m:
        yield m


def sent(route):
    req = route.calls.last.request
    return req, json.loads(req.content or b"{}")


# ------------------------------------------------------------------ install / package

@case("PY-INS-01", "Install", "Package installs from PyPI and reports its version")
def test_version():
    assert aivana.__version__ and aivana.__version__ != "0.0.0+local"


@case("PY-INS-02", "Install", "Runs on the documented minimum (Python >= 3.10)")
def test_python_version():
    assert sys.version_info >= (3, 10)


@case("PY-INS-03", "Install", "Every name the docs use is importable from `aivana`")
def test_public_api():
    for name in ["generate", "generate_async", "generate_stream", "Chat", "set_api_key",
                 "set_api_base", "GenerateResponse", "StreamChunk", "Notice", "AivanaError",
                 "AuthError", "ForbiddenError", "RateLimitError", "InvalidRequestError",
                 "UpstreamError"]:
        assert hasattr(aivana, name), name


# ------------------------------------------------------------------ configuration

@case("PY-CFG-01", "Configure", "`aivana.api_key = ...` (Docs > SDKs example) sends X-API-Key")
def test_api_key_assignment(api):
    r = api.post("/v1/generate").respond(200, json=REAL_OK)
    aivana.api_key = "ai_test_assign"
    aivana.generate("hi")
    assert sent(r)[0].headers["X-API-Key"] == "ai_test_assign"
    assert aivana.api_key == "ai_test_assign"


@case("PY-CFG-02", "Configure", "`set_api_key()` is equivalent to assignment")
def test_set_api_key(api):
    r = api.post("/v1/generate").respond(200, json=REAL_OK)
    aivana.set_api_key("ai_test_setter")
    aivana.generate("hi")
    assert sent(r)[0].headers["X-API-Key"] == "ai_test_setter"


@case("PY-CFG-03", "Configure", "Falls back to AIVANA_API_KEY, read per request (export after import)")
def test_env_fallback(api, monkeypatch):
    r = api.post("/v1/generate").respond(200, json=REAL_OK)
    monkeypatch.setenv("AIVANA_API_KEY", "ai_test_env")
    aivana.generate("hi")
    assert sent(r)[0].headers["X-API-Key"] == "ai_test_env"


@case("PY-CFG-04", "Configure", "A key set in code wins over AIVANA_API_KEY")
def test_code_key_wins(api, monkeypatch):
    r = api.post("/v1/generate").respond(200, json=REAL_OK)
    monkeypatch.setenv("AIVANA_API_KEY", "ai_test_env")
    aivana.api_key = "ai_test_code"
    aivana.generate("hi")
    assert sent(r)[0].headers["X-API-Key"] == "ai_test_code"


@case("PY-CFG-05", "Configure", "No key anywhere: no header sent, 401 surfaces as AuthError")
def test_no_key(api):
    r = api.post("/v1/generate").respond(401, json=REAL_401)
    with pytest.raises(AuthError) as e:
        aivana.generate("hi")
    assert "X-API-Key" not in sent(r)[0].headers
    assert e.value.code == "invalid_api_key"


@case("PY-CFG-06", "Configure", "Default api_base is the documented hosted API; trailing slash normalised")
def test_api_base(offline):
    from aivana import client
    import importlib
    fresh = importlib.reload(client)  # defaults as shipped
    try:
        assert fresh.api_base == DOCUMENTED_DEFAULT_BASE
    finally:
        aivana.set_api_base(OFFLINE_BASE)
    aivana.api_base = "https://example.test/"
    assert aivana.api_base == "https://example.test"
    aivana.set_api_base(OFFLINE_BASE)


@case("PY-CFG-07", "Configure", "Docs > SDKs configure snippet works when the env var is unset")
@pytest.mark.xfail(strict=True, reason="F9: docs snippet os.environ['AIVANA_API_KEY'] raises KeyError "
                   "when unset; SDK already reads the env var itself")
def test_docs_configure_snippet(offline):
    import os
    aivana.api_key = os.environ["AIVANA_API_KEY"]   # verbatim from Docs > SDKs > Configure


# ------------------------------------------------------------------ generate

@case("PY-GEN-01", "Generate", "Parses a real dev-API response: answer, usage, finish_reason, notices")
def test_generate_parses(api):
    api.post("/v1/generate").respond(200, json=REAL_OK)
    res = aivana.generate("Write a haiku about the ocean.")
    assert isinstance(res, GenerateResponse)
    assert res.answer.startswith("Moon")
    assert res.usage.output_tokens == 23 and res.finish_reason == "stop"
    assert res.notices == [] and res.request_id.startswith("req_")


@case("PY-GEN-02", "Generate", "POSTs /v1/generate with prompt; unset options are omitted")
def test_generate_minimal_body(api):
    r = api.post("/v1/generate").respond(200, json=REAL_OK)
    aivana.generate("hello")
    req, body = sent(r)
    assert req.url.path == "/v1/generate"
    assert body == {"mode": "aivana_mmi", "prompt": "hello"}


@case("PY-GEN-03", "Generate", "Every documented option reaches the wire in snake_case")
def test_generate_options(api):
    r = api.post("/v1/generate").respond(200, json=REAL_OK)
    aivana.generate("q", effort="HIGH", web_search=False, top_p=0.0, temperature=0.2,
                    max_tokens=50, stop_sequences=["###"], intelligence_trace=True,
                    output_shape="summary", system="Be brief.", assistant_name="Acme",
                    metadata={"k": "v"})
    _, b = sent(r)
    assert b["effort"] == "high"
    assert b["web_search"] is False                  # three-state: False must be sent
    assert b["top_p"] == 0.0                         # 0.0 is legal, must not be dropped
    assert b["temperature"] == 0.2 and b["max_tokens"] == 50
    assert b["stop_sequences"] == ["###"] and b["intelligence_trace"] is True
    assert b["output_shape"] == "summary" and b["system"] == "Be brief."
    assert b["assistant_name"] == "Acme" and b["metadata"] == {"k": "v"}


@case("PY-GEN-04", "Generate", "System prompt > 8000 chars raises InvalidRequestError before any request")
def test_system_limit(api):
    r = api.post("/v1/generate").respond(200, json=REAL_OK)
    with pytest.raises(InvalidRequestError):
        aivana.generate("q", system="x" * 8001)
    assert not r.called


@case("PY-GEN-05", "Generate", "Attachments: mimeType normalised to mime_type; bad item rejected")
def test_attachments(api):
    r = api.post("/v1/generate").respond(200, json=REAL_OK)
    aivana.generate("q", attachments=[{"mimeType": "image/png", "data": "AAAA"}])
    assert sent(r)[1]["attachments"] == [{"mime_type": "image/png", "data": "AAAA"}]
    with pytest.raises(InvalidRequestError):
        aivana.generate("q", attachments=["not-a-dict"])


@case("PY-GEN-06", "Generate", "response_format sent exactly as given; non-dict rejected client-side")
def test_response_format(api):
    r = api.post("/v1/generate").respond(200, json=REAL_OK)
    fmt = {"type": "json_schema", "schema": {"type": "object", "properties": {"vendorName": {"type": "string"}}}}
    aivana.generate("q", response_format=fmt)
    assert sent(r)[1]["response_format"] == fmt
    with pytest.raises(InvalidRequestError):
        aivana.generate("q", response_format="json")


@case("PY-GEN-07", "Generate", "Tolerates new fields the server adds (forward compatible)")
def test_forward_compat(api):
    api.post("/v1/generate").respond(200, json={**REAL_OK, "brand_new_field": {"x": 1}})
    assert aivana.generate("q").answer


@case("PY-GEN-08", "Generate", "Non-JSON 200 (proxy page) raises AivanaError, not JSONDecodeError")
def test_non_json(api):
    api.post("/v1/generate").respond(200, text="<html>gateway</html>")
    with pytest.raises(AivanaError) as e:
        aivana.generate("q")
    assert e.value.code == "invalid_response"


@case("PY-GEN-09", "Generate", "Redirects are not followed, so the key never leaves api_base")
def test_redirect(api):
    api.post("/v1/generate").respond(307, headers={"Location": "https://evil.test/v1/generate"})
    with pytest.raises(AivanaError) as e:
        aivana.generate("q")
    assert e.value.code == "redirect"


@case("PY-GEN-10", "Generate", "generate_async returns the same GenerateResponse")
def test_generate_async(api):
    api.post("/v1/generate").respond(200, json=REAL_OK)
    res = asyncio.run(aivana.generate_async("q"))
    assert res.answer.startswith("Moon")


@case("PY-GEN-11", "Generate", "messages= is sent instead of prompt (manual history)")
def test_messages(api):
    r = api.post("/v1/generate").respond(200, json=REAL_OK)
    msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"}]
    aivana.generate(messages=msgs, previous_intent="creative")
    _, b = sent(r)
    assert b["messages"] == msgs and "prompt" not in b and b["previous_intent"] == "creative"


# ------------------------------------------------------------------ streaming

STREAM_OK = sse(("delta", {"text": "Hello "}), ("delta", {"text": "world"}),
                ("done", {"usage": {"input_tokens": 3, "output_tokens": 2}, "finish_reason": "stop",
                          "notices": []}))


@case("PY-STR-01", "Streaming", "stream=True yields delta chunks that join into the answer; done carries usage")
def test_stream(api):
    api.post("/v1/generate:stream").respond(200, text=STREAM_OK,
                                             headers={"Content-Type": "text/event-stream"})
    chunks = list(aivana.generate("q", stream=True))
    assert all(isinstance(c, StreamChunk) for c in chunks)
    assert "".join(c.delta for c in chunks) == "Hello world"
    done = [c for c in chunks if c.event == "done"][0]
    assert done.data["finish_reason"] == "stop" and "notices" in done.data


@case("PY-STR-02", "Streaming", "Streams hit POST /v1/generate:stream with the same body")
def test_stream_endpoint(api):
    r = api.post("/v1/generate:stream").respond(200, text=STREAM_OK)
    list(aivana.generate("q", stream=True, effort="low"))
    req, b = sent(r)
    assert req.url.path == "/v1/generate:stream" and b["effort"] == "low"


@case("PY-STR-03", "Streaming", "json_schema + stream refused client-side with the documented code")
def test_stream_strict_refused(api):
    r = api.post("/v1/generate:stream").respond(200, text=STREAM_OK)
    with pytest.raises(InvalidRequestError) as e:
        aivana.generate("q", stream=True, response_format={"type": "json_schema", "schema": {}})
    assert e.value.code == "structured_output_streaming_not_supported" and not r.called


@case("PY-STR-04", "Streaming", "HTTP 401 on the stream raises AuthError (not an httpx error)")
def test_stream_401(api):
    api.post("/v1/generate:stream").respond(401, json=REAL_401)
    with pytest.raises(AuthError):
        list(aivana.generate("q", stream=True))


@case("PY-STR-05", "Streaming", "Async generate_stream yields the same chunks")
def test_generate_stream_async(api):
    api.post("/v1/generate:stream").respond(200, text=STREAM_OK)

    async def go():
        return [c async for c in aivana.generate_stream("q")]
    assert "".join(c.delta for c in asyncio.run(go())) == "Hello world"


@case("PY-STR-06", "Streaming", "Unknown/trace events pass through without breaking iteration")
def test_stream_unknown_events(api):
    body = sse(("trace", {"step": {"status": "started", "title": "Understanding Request"}}),
               ("future_event", {"x": 1}), ("delta", {"text": "ok"}), ("done", {}))
    api.post("/v1/generate:stream").respond(200, text=body)
    chunks = list(aivana.generate("q", stream=True, intelligence_trace=True))
    assert [c.event for c in chunks] == ["trace", "future_event", "delta", "done"]


@case("PY-STR-07", "Streaming", "Mid-stream `error` event raises AivanaError ('every failure raises')")
@pytest.mark.xfail(strict=True, reason="F1: a mid-stream error event is yielded as an ordinary chunk; "
                   "the documented `for chunk: print(chunk.delta)` loop ends silently with a partial answer")
def test_stream_error_event(api):
    body = sse(("delta", {"text": "partial"}),
               ("error", {"code": "upstream", "message": "engine failed", "request_id": "req_x"}))
    api.post("/v1/generate:stream").respond(200, text=body)
    with pytest.raises(AivanaError):
        for chunk in aivana.generate("q", stream=True):
            print(chunk.delta, end="")


# ------------------------------------------------------------------ errors

@pytest.mark.parametrize("status,body,cls,code", [
    (401, REAL_401, AuthError, "invalid_api_key"),
    (403, err("forbidden"), ForbiddenError, "forbidden"),
    (400, err("invalid_request"), InvalidRequestError, "invalid_request"),
    (422, err("invalid_response_schema", details=[{"loc": ["schema"], "msg": "bad", "type": "x"}]),
     InvalidRequestError, "invalid_response_schema"),
    (429, err("rate_limit_exceeded", retry_after_ms=12000), RateLimitError, "rate_limit_exceeded"),
    (429, err("spend_limit_reached"), RateLimitError, "spend_limit_reached"),
    (502, err("structured_output_failed"), UpstreamError, "structured_output_failed"),
    (402, err("insufficient_credit"), AivanaError, "insufficient_credit"),
])
@case("PY-ERR-01", "Errors", "Each documented status maps to the documented AivanaError subclass + code")
def test_error_mapping(api, status, body, cls, code):
    api.post("/v1/generate").respond(status, json=body)
    with pytest.raises(cls) as e:
        aivana.generate("q")
    assert isinstance(e.value, AivanaError) and e.value.code == code and e.value.message


@case("PY-ERR-02", "Errors", "422 details (which field is wrong) are kept on the exception")
def test_error_details(api):
    d = [{"loc": ["body", "temperature"], "msg": "<= 2", "type": "less_than_equal"}]
    api.post("/v1/generate").respond(422, json=err("invalid_response_schema", details=d))
    with pytest.raises(InvalidRequestError) as e:
        aivana.generate("q")
    assert e.value.details == d and e.value.request_id == "req_test"


@case("PY-ERR-03", "Errors", "Any 422 is an InvalidRequestError (docs: '400 or 422')")
@pytest.mark.xfail(strict=True, reason="F3: a 422 whose code is not on the SDK's allowlist "
                   "(e.g. a generic validation error) falls through to base AivanaError")
def test_422_generic(api):
    api.post("/v1/generate").respond(422, json=err("validation_error"))
    with pytest.raises(InvalidRequestError):
        aivana.generate("q", temperature=5)


@case("PY-ERR-04", "Errors", "request_id is available on errors (falls back to X-Request-Id header)")
@pytest.mark.xfail(strict=True, reason="F4: the live 401 body has no request_id and the SDK does not "
                   "read the X-Request-Id header, so err.request_id is None")
def test_request_id_header(api):
    api.post("/v1/generate").respond(401, json=REAL_401, headers={"X-Request-Id": "req_from_header"})
    with pytest.raises(AuthError) as e:
        aivana.generate("q")
    assert e.value.request_id == "req_from_header"


@case("PY-ERR-05", "Errors", "Network failure raises an AivanaError subclass ('every failure raises')")
@pytest.mark.xfail(strict=True, reason="F5: httpx.ConnectError escapes unwrapped; `except AivanaError` misses it")
def test_network_error(api):
    api.post("/v1/generate").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(AivanaError):
        aivana.generate("q")


@case("PY-ERR-06", "Errors", "Timeout raises an AivanaError subclass")
@pytest.mark.xfail(strict=True, reason="F5: httpx.ReadTimeout escapes unwrapped")
def test_timeout(api):
    api.post("/v1/generate").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(AivanaError):
        aivana.generate("q")


@case("PY-ERR-07", "Errors", "RateLimitError exposes the Retry-After wait the docs say to honour")
@pytest.mark.xfail(strict=True, reason="F6: retry_after_ms / Retry-After are dropped; no attribute on the error")
def test_retry_after(api):
    api.post("/v1/generate").respond(429, json=err("rate_limit_exceeded", retry_after_ms=12000),
                                     headers={"Retry-After": "12"})
    with pytest.raises(RateLimitError) as e:
        aivana.generate("q")
    assert getattr(e.value, "retry_after_ms", None) == 12000 or getattr(e.value, "retry_after", None) == 12


@case("PY-ERR-08", "Errors", "504 (documented retryable) raises a catchable, retryable error class")
@pytest.mark.xfail(strict=True, reason="F7: 504 (and 413/500/503) become base AivanaError; only 502 is "
                   "UpstreamError, so the docs' `except (RateLimitError, UpstreamError)` retry misses 504")
def test_504(api):
    api.post("/v1/generate").respond(504, json=err("timeout"))
    with pytest.raises((RateLimitError, UpstreamError)):
        aivana.generate("q")


# ------------------------------------------------------------------ Chat

def _ok(answer, intent="general", pending=None):
    return {**REAL_OK, "answer": answer, "intent": {"name": intent, "confidence": 1.0},
            "pending_action": pending}


@case("PY-CHT-01", "Conversations", "Chat sends full history plus previous_intent / pending_action")
def test_chat_history(api):
    r = api.post("/v1/generate")
    r.side_effect = [httpx.Response(200, json=_ok("A1", "advice", "offer_example")),
                     httpx.Response(200, json=_ok("A2"))]
    chat = Chat()
    chat.send("Q1")
    chat.send("Q2")
    _, b = sent(r)
    assert [m["content"] for m in b["messages"]] == ["Q1", "A1", "Q2"]
    assert b["previous_intent"] == "advice" and b["pending_action"] == "offer_example"


@case("PY-CHT-02", "Conversations", "Chat options apply every turn; send() overrides win for that turn")
def test_chat_options(api):
    r = api.post("/v1/generate").respond(200, json=_ok("A"))
    chat = Chat(system="Three bullets.", web_search=True)
    chat.send("Q1")
    assert sent(r)[1]["system"] == "Three bullets." and sent(r)[1]["web_search"] is True
    chat.send("Q2", web_search=False)
    assert sent(r)[1]["web_search"] is False and sent(r)[1]["system"] == "Three bullets."


@case("PY-CHT-03", "Conversations", "reset() starts a fresh conversation")
def test_chat_reset(api):
    r = api.post("/v1/generate").respond(200, json=_ok("A"))
    chat = Chat()
    chat.send("Q1")
    chat.reset()
    chat.send("Q2")
    assert [m["content"] for m in sent(r)[1]["messages"]] == ["Q2"]


@case("PY-CHT-04", "Conversations", "A failed send() does not corrupt history (retry is safe)")
@pytest.mark.xfail(strict=True, reason="F8: the user turn is appended before the request; on error it stays, "
                   "so retrying send() sends the question twice")
def test_chat_failed_send(api):
    r = api.post("/v1/generate")
    r.side_effect = [httpx.Response(502, json=err("upstream")), httpx.Response(200, json=_ok("A"))]
    chat = Chat()
    with pytest.raises(UpstreamError):
        chat.send("Q1")
    chat.send("Q1")                                  # the natural retry
    assert [m["content"] for m in sent(r)[1]["messages"]] == ["Q1"]
