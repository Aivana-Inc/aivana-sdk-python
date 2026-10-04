"""Strict JSON Schema output (`response_format`): what the SDK sends and refuses.

The API either answers with a `structured` object that validates against the
caller's schema or fails, so this client's jobs are small and easy to get wrong
silently: send the schema EXACTLY as given (its keys are the caller's own field
names), refuse to stream it (before any network call), and raise the errors the
API sends as the classes a caller catches. Parity with @aivana/sdk is pinned in
its test/structured.test.mjs; the wire body is also pinned by test_parity.py.

    python3 -m pytest tests/ -q
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aivana  # noqa: E402
from aivana import client as c  # noqa: E402
from aivana.client import _body  # noqa: E402
from aivana.exceptions import from_error_payload  # noqa: E402

# camelCase keys, a nested object, an array: anything that would show a re-casing,
# a re-ordering or a dropped key.
SCHEMA = {
    "type": "object",
    "properties": {
        "vendorName": {"type": "string"},
        "lineItems": {
            "type": "array",
            "items": {"type": "object", "properties": {"unitPrice": {"type": "number"}}},
        },
    },
    "required": ["vendorName"],
    "additionalProperties": False,
}
STRICT = {"type": "json_schema", "schema": SCHEMA}
VALID = {"vendorName": "Acme", "lineItems": [{"unitPrice": 12.5}]}


def _envelope(code, **extra):
    return {"error": {"type": code, "code": code, "message": "nope",
                      "request_id": "req_1", **extra}}


@pytest.fixture
def no_network(monkeypatch):
    """Any request at all fails the test: the guards must act before one is made."""
    def boom(**kw):
        raise AssertionError("a request was made")
    monkeypatch.setattr(c.httpx, "Client", boom)
    monkeypatch.setattr(c.httpx, "AsyncClient", boom)


@pytest.fixture
def sent(monkeypatch):
    """The real SDK over a fake API that records bodies and answers a strict run."""
    bodies = []

    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "gen_1", "request_id": "req_1",
            "answer": json.dumps(VALID, separators=(",", ":")),
            "structured": VALID,
            "intent": {"name": "general", "confidence": 1.0},
            "models_used": ["aivana-mmi"],
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "latency_ms": 1, "finish_reason": "stop", "notices": [],
        })

    real = httpx.Client
    monkeypatch.setattr(c.httpx, "Client",
                        lambda **kw: real(transport=httpx.MockTransport(handle), **kw))
    return bodies


# ---- the wire ------------------------------------------------------------------

def test_omitted_unless_the_caller_sets_it():
    assert "response_format" not in _body("hi")


def test_the_schema_is_sent_exactly_as_given():
    sent_schema = _body("hi", response_format=STRICT)["response_format"]["schema"]
    assert sent_schema == SCHEMA
    # Same keys in the same order, at every level: a dict compares equal in any
    # order, but the caller's field order is part of what they wrote.
    assert json.dumps(sent_schema) == json.dumps(SCHEMA)


def test_the_callers_dict_is_never_mutated():
    fmt = copy.deepcopy(STRICT)
    body = _body("hi", response_format=fmt)
    body["response_format"]["type"] = "changed"
    assert fmt == STRICT, "the wrapper must be a copy"


def test_a_text_format_is_sent_as_it_is():
    assert _body("hi", response_format={"type": "text"})["response_format"] == {"type": "text"}


def test_it_is_not_confused_with_output_shape():
    body = _body("hi", response_format=STRICT)
    assert "output_shape" not in body


def test_a_non_object_is_refused_before_any_request(no_network):
    for bad in ("json_schema", ["json_schema"], 7, True):
        with pytest.raises(aivana.InvalidRequestError) as e:
            aivana.generate("hi", response_format=bad)
        assert e.value.code == "invalid_request"


def test_a_whole_call_sends_it_and_returns_the_validated_object(sent):
    resp = aivana.generate("Extract the invoice.", response_format=STRICT)
    assert sent[0]["response_format"] == STRICT
    assert resp.structured == VALID
    assert json.loads(resp.answer) == VALID


def test_chat_sends_it_on_every_turn(sent):
    chat = aivana.Chat(response_format=STRICT)
    chat.send("first")
    chat.send("second")
    assert [b["response_format"] for b in sent] == [STRICT, STRICT]


# ---- streaming ----------------------------------------------------------------

def test_a_strict_schema_cannot_be_streamed_and_no_request_is_made(no_network):
    with pytest.raises(aivana.InvalidRequestError) as e:
        aivana.generate("hi", stream=True, response_format=STRICT)
    assert e.value.code == "structured_output_streaming_not_supported"


def test_the_async_stream_refuses_it_too(no_network):
    async def first():
        async for _ in aivana.generate_stream("hi", response_format=STRICT):
            break

    with pytest.raises(aivana.InvalidRequestError) as e:
        asyncio.run(first())
    assert e.value.code == "structured_output_streaming_not_supported"


def test_a_plain_text_format_may_still_stream(no_network):
    # No network until the stream is read: building it must not raise.
    stream = aivana.generate("hi", stream=True, response_format={"type": "text"})
    assert hasattr(stream, "__next__")


# ---- errors -------------------------------------------------------------------

@pytest.mark.parametrize("code", ["invalid_response_schema", "response_format_not_available",
                                  "structured_output_streaming_not_supported"])
def test_a_refused_request_is_the_callers_to_fix(code):
    err = from_error_payload(_envelope(code), 422)
    assert isinstance(err, aivana.InvalidRequestError)
    assert err.code == code


def test_a_failed_run_is_an_upstream_error_with_its_own_code():
    err = from_error_payload(_envelope("structured_output_failed"), 502)
    assert isinstance(err, aivana.UpstreamError)
    assert err.code == "structured_output_failed"


def test_other_422_codes_are_unchanged():
    # Only the two codes above joined the class: an unknown 422 is still generic.
    assert type(from_error_payload(_envelope("something_new"), 422)) is aivana.AivanaError
