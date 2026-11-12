"""Live validation against the Aivana API, used as an external developer would.

Needs AIVANA_API_KEY (a sponsor-approved test key). Defaults to the dev host
https://dev-developers.aivana.ai; override with AIVANA_API_BASE.
Calls use effort="low" and small max_tokens, so a full run costs a few cents of credit
at most. Redacted evidence for each call is written to results/evidence.jsonl.
"""
from __future__ import annotations

import asyncio
import time

import pytest

import aivana
from aivana import AivanaError, AuthError, Chat, InvalidRequestError

from conftest import CHEAP, DOCUMENTED_DEFAULT_BASE

case = pytest.mark.case
pytestmark = pytest.mark.live


def summary(res):
    return {"id": res.id, "request_id": res.request_id, "finish_reason": res.finish_reason,
            "usage": res.usage.model_dump(), "latency_ms": res.latency_ms,
            "notices": [n.model_dump() for n in res.notices], "models_used": res.models_used,
            "answer_preview": res.answer[:160], "has_trace": res.trace is not None,
            "structured": res.structured, "structured_error": res.structured_error}


def err_summary(e):
    return {"class": type(e).__name__, "code": getattr(e, "code", None),
            "message": getattr(e, "message", str(e))[:200], "request_id": getattr(e, "request_id", None),
            "details": getattr(e, "details", None)}


# ------------------------------------------------------------------ auth / environment

@case("PY-LIV-01", "Auth", "Invalid key -> AuthError with code, message and request_id")
def test_invalid_key(live, evidence, monkeypatch):
    monkeypatch.setenv("AIVANA_API_KEY", "ai_test_definitely_not_a_real_key_000")
    with pytest.raises(AuthError) as e:
        aivana.generate("ping", **CHEAP)
    evidence(base=live, error=err_summary(e.value))
    assert e.value.code and e.value.message
    # request_id is documented as "always present"; recorded, checked by PY-LIV-02.


@case("PY-LIV-02", "Auth", "Errors carry the request_id the docs say to quote to support (dev host)")
def test_error_request_id(live, monkeypatch):
    monkeypatch.setenv("AIVANA_API_KEY", "ai_test_definitely_not_a_real_key_000")
    with pytest.raises(AuthError) as e:
        aivana.generate("ping", **CHEAP)
    assert e.value.request_id


@case("PY-LIV-03", "Auth", "A test key on the default (production) host is refused, and the error says it is from another environment (Docs > API Keys)")
@pytest.mark.xfail(strict=False, reason="F2: refusing ai_test_ keys on api.aivana.ai is by design (Docs > API Keys), but "
                   "the 401 says 'Invalid or expired API key. Generate a new key', not that the key is from another environment")
def test_default_base(live, evidence):
    aivana.set_api_base(DOCUMENTED_DEFAULT_BASE)
    with pytest.raises(AuthError) as e:
        aivana.generate("Reply with the single word: ok", **CHEAP)
    evidence(base=DOCUMENTED_DEFAULT_BASE, error=err_summary(e.value))
    msg = e.value.message.lower()
    assert "environment" in msg or "test key" in msg, e.value.message


@case("PY-LIV-04", "Auth", "Errors from the default (production) host also carry request_id")
@pytest.mark.xfail(strict=False, reason="F4: the production host's 401 body has no request_id and the SDK "
                   "does not fall back to the X-Request-Id header (dev host does include it)")
def test_default_base_request_id(live, evidence, monkeypatch):
    aivana.set_api_base(DOCUMENTED_DEFAULT_BASE)
    monkeypatch.setenv("AIVANA_API_KEY", "ai_test_definitely_not_a_real_key_000")
    with pytest.raises(AuthError) as e:
        aivana.generate("ping", **CHEAP)
    evidence(base=DOCUMENTED_DEFAULT_BASE, error=err_summary(e.value))
    assert e.value.request_id


# ------------------------------------------------------------------ generate

@case("PY-LIV-10", "Generate", "Basic generate (Docs > SDKs example) returns answer, usage, finish_reason, notices")
def test_basic(live, evidence):
    t = time.time()
    res = aivana.generate("Write a haiku about the ocean.", **CHEAP)
    evidence(response=summary(res), wall_s=round(time.time() - t, 2))
    assert res.answer.strip()
    assert res.id and res.request_id
    assert res.usage.input_tokens > 0 and res.usage.output_tokens > 0
    assert res.finish_reason in ("stop", "length")
    assert isinstance(res.notices, list)


@case("PY-LIV-11", "Generate", "max_tokens is a ceiling: output_tokens <= max_tokens")
@pytest.mark.xfail(strict=False, reason="F11: max_tokens=40 returned 67 output tokens (billed) with "
                   "finish_reason=stop on Oct 5; docs call max_tokens a ceiling")
def test_max_tokens(live, evidence):
    res = aivana.generate("Explain TCP vs UDP in detail.", effort="low", max_tokens=40)
    evidence(response=summary(res))
    assert res.usage.output_tokens <= 40 + 5     # small tolerance for tokenizer differences


@case("PY-LIV-12", "Generate", "intelligence_trace=True returns trace with steps and summary")
def test_trace(live, evidence):
    res = aivana.generate("Is Postgres or DynamoDB better for a write-heavy API?",
                          intelligence_trace=True, **CHEAP)
    evidence(response=summary(res), trace_keys=sorted((res.trace or {}).keys()),
             step_titles=[s.get("title") for s in (res.trace or {}).get("steps", [])])
    assert res.trace and res.trace.get("steps") and res.trace.get("summary")


@case("PY-LIV-13", "Generate", "Trace stays customer-safe: no provider/model names leak")
def test_trace_ip_boundary(live, evidence):
    res = aivana.generate("Compare two approaches to caching.", intelligence_trace=True, **CHEAP)
    blob = str(res.trace).lower() + " " + " ".join(res.models_used).lower()
    leaked = [w for w in ("gpt", "claude", "gemini", "llama", "mistral", "openai", "anthropic")
              if w in blob]
    evidence(models_used=res.models_used, leaked_terms=leaked)
    assert not leaked


@case("PY-LIV-14", "Generate", "assistant_name is honoured")
def test_assistant_name(live, evidence):
    res = aivana.generate("Who are you? One sentence.", assistant_name="Acme Copilot", **CHEAP)
    evidence(response=summary(res))
    assert "acme" in res.answer.lower()


@case("PY-LIV-15", "Generate", "messages= with a system message works (manual history)")
def test_messages_system(live, evidence):
    res = aivana.generate(messages=[
        {"role": "system", "content": "Always answer in exactly three words."},
        {"role": "user", "content": "My favourite colour is teal."},
        {"role": "assistant", "content": "Teal is lovely."},
        {"role": "user", "content": "What is my favourite colour?"}], **CHEAP)
    evidence(response=summary(res))
    assert "teal" in res.answer.lower()


@case("PY-LIV-16", "Generate", "web_search off + a question asking for the web -> web_search_off notice")
def test_web_search_notice(live, evidence):
    res = aivana.generate("Search the web for today's top tech headline.", web_search=False, **CHEAP)
    evidence(response=summary(res))
    assert any(n.code == "web_search_off" for n in res.notices)


@case("PY-LIV-17", "Generate", "stop_sequences: the marker is not returned")
def test_stop_sequences(live, evidence):
    res = aivana.generate("Print the numbers 1 to 10 separated by commas.",
                          stop_sequences=["5"], **CHEAP)
    evidence(response=summary(res))
    assert "5" not in res.answer and "6" not in res.answer


@case("PY-LIV-18", "Generate", "output_shape='extract' returns structured or structured_error")
def test_output_shape(live, evidence):
    res = aivana.generate("Invoice INV-204 from Acme Ltd, total due 1,250.00 USD.",
                          output_shape="extract", temperature=0, **CHEAP)
    evidence(response=summary(res))
    assert res.structured is not None or res.structured_error is not None


SCHEMA = {"type": "object", "properties": {"vendorName": {"type": "string"}, "total": {"type": "number"}},
          "required": ["vendorName", "total"], "additionalProperties": False}


@case("PY-LIV-19", "Structured", "response_format json_schema -> validated .structured, or documented "
      "response_format_not_available")
def test_json_schema(live, evidence):
    try:
        res = aivana.generate("Extract the invoice: Acme Ltd, total due 1,250.00",
                              response_format={"type": "json_schema", "schema": SCHEMA}, max_tokens=200)
    except InvalidRequestError as e:
        evidence(error=err_summary(e))
        assert e.code == "response_format_not_available", e.code
        pytest.skip("JSON Schema (Strict) not served on this environment")
    evidence(response=summary(res))
    assert set(res.structured) == {"vendorName", "total"}
    assert isinstance(res.structured["total"], (int, float))


@case("PY-LIV-22", "Structured", "A successful json_schema answer reports its output tokens in usage")
@pytest.mark.xfail(strict=False, reason="F13: Oct 5 json_schema success returned an answer with "
                   "usage.output_tokens=0 (credits = input only) - metering or reporting gap")
def test_json_schema_usage(live, evidence):
    try:
        res = aivana.generate("Extract the invoice: Acme Ltd, total due 1,250.00",
                              response_format={"type": "json_schema", "schema": SCHEMA}, max_tokens=200)
    except InvalidRequestError as e:
        pytest.skip(f"JSON Schema not served here ({e.code})")
    evidence(response=summary(res))
    assert res.usage.output_tokens > 0


@case("PY-LIV-20", "Structured", "Unsupported schema -> InvalidRequestError invalid_response_schema, not billed")
def test_bad_schema(live, evidence):
    with pytest.raises(InvalidRequestError) as e:
        aivana.generate("x", response_format={"type": "json_schema", "schema": {"type": "array"}})
    evidence(error=err_summary(e.value))
    assert e.value.code in ("invalid_response_schema", "response_format_not_available")


@case("PY-LIV-21", "Errors", "Out-of-range parameter (temperature=5) -> InvalidRequestError with details")
def test_bad_param(live, evidence):
    try:
        aivana.generate("x", temperature=5, **CHEAP)
    except AivanaError as e:
        evidence(error=err_summary(e))
        assert isinstance(e, InvalidRequestError), f"got {type(e).__name__} code={e.code} (see F3)"
        return
    pytest.fail("temperature=5 was accepted; docs say 0.0-2.0")


# ------------------------------------------------------------------ streaming / async / chat

@case("PY-LIV-23", "Generate", "effort is a ceiling: effort='low' keeps a decision question below the top level (Premium)")
@pytest.mark.xfail(strict=False, reason="F16: on 2026-10-20 effort=low and effort=high gave the same intelligence_level "
                   "(Premium), route and 3 perspectives on two decision questions; low did not bound anything")
def test_effort_low_is_a_ceiling(live, evidence):
    res = aivana.generate("Should we move billing off Stripe before the Series A? One sentence.",
                          effort="low", intelligence_trace=True, max_tokens=60)
    s = (res.trace or {}).get("summary", {})
    evidence(response=summary(res), intelligence_level=s.get("intelligence_level"), route=s.get("route"),
             perspectives=s.get("perspectives"))
    assert s.get("intelligence_level") != "Premium"


@case("PY-LIV-30", "Streaming", "stream=True: deltas arrive incrementally and done carries usage/notices")
def test_stream(live, evidence):
    t0, first, chunks = time.time(), None, []
    for c in aivana.generate("Count from 1 to 15, one number per line.", stream=True, **CHEAP):
        if c.event == "delta" and first is None:
            first = time.time() - t0
        chunks.append(c)
    events = [c.event for c in chunks]
    done = next((c for c in chunks if c.event == "done"), None)
    samples = {}
    for c in chunks:
        if c.event not in ("delta", "done") and c.event not in samples:
            samples[c.event] = c.data
    evidence(events=sorted(set(events)), n_delta=events.count("delta"), other_event_samples=samples,
             time_to_first_delta_s=round(first or -1, 2), total_s=round(time.time() - t0, 2),
             done=done.data if done else None)
    assert events.count("delta") >= 2 and done is not None
    assert "usage" in done.data and "finish_reason" in done.data and "notices" in done.data


DOCUMENTED_EVENTS = {"delta", "done", "error"}
LEAK_TERMS = ("gpt", "claude", "gemini", "llama", "mistral", "openai", "anthropic", "grok", "deepseek")


@case("PY-LIV-34", "Streaming", "Without intelligence_trace, a stream sends only documented events")
@pytest.mark.xfail(strict=False, reason="F14: every stream also carries undocumented `route` and `stage` "
                   "events (and `model` on done), even with intelligence_trace off")
def test_stream_undocumented_events(live, evidence):
    chunks = list(aivana.generate("Name three prime numbers.", stream=True, **CHEAP))
    extra = {}
    for c in chunks:
        if c.event not in DOCUMENTED_EVENTS:
            extra.setdefault(c.event, []).append(c.data)
    evidence(undocumented_events={k: v[:3] for k, v in extra.items()})
    assert not extra


@case("PY-LIV-35", "Streaming", "Stream route/stage/trace payloads stay customer-safe (no model/provider names)")
def test_stream_payload_ip_boundary(live, evidence):
    chunks = list(aivana.generate("Compare REST and GraphQL briefly.", stream=True,
                                  intelligence_trace=True, **CHEAP))
    blob = " ".join(str(c.data) for c in chunks if c.event != "delta").lower()
    leaked = [w for w in LEAK_TERMS if w in blob]
    evidence(non_delta_events=sorted({c.event for c in chunks if c.event != "delta"}), leaked_terms=leaked)
    assert not leaked


@case("PY-LIV-31", "Streaming", "stream + intelligence_trace emits trace events")
def test_stream_trace(live, evidence):
    evs = [c.event for c in aivana.generate("Pros and cons of microservices?", stream=True,
                                            intelligence_trace=True, **CHEAP)]
    evidence(events=sorted(set(evs)), n_trace=evs.count("trace"))
    assert "trace" in evs


@case("PY-LIV-32", "Streaming", "Invalid key on the stream raises AuthError")
def test_stream_bad_key(live, monkeypatch):
    monkeypatch.setenv("AIVANA_API_KEY", "ai_test_definitely_not_a_real_key_000")
    with pytest.raises(AuthError):
        list(aivana.generate("x", stream=True, **CHEAP))


@case("PY-LIV-33", "Async", "generate_async and generate_stream work end to end")
def test_async(live, evidence):
    async def go():
        res = await aivana.generate_async("Say hi in one word.", **CHEAP)
        text = "".join([c.delta async for c in aivana.generate_stream("Say bye in one word.", **CHEAP)])
        return res, text
    res, text = asyncio.run(go())
    evidence(async_answer=res.answer[:80], stream_text=text[:80])
    assert res.answer.strip() and text.strip()


@case("PY-LIV-40", "Conversations", "Chat remembers earlier turns (Docs > SDKs > Conversations)")
def test_chat(live, evidence):
    chat = Chat(system="Answer in one short sentence.", **CHEAP)
    chat.send("My project codename is BLUE HERON.")
    res = chat.send("What is my project codename?")
    evidence(turns=len(chat.messages), answer=res.answer[:120])
    assert "heron" in res.answer.lower()
