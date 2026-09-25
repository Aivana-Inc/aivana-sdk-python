"""The error envelope: which class a caller catches, and what survives on it.

The API answers a schema violation with 422 — not 400 — and its `details` list is
the only part of the response that says WHICH field is wrong. Both are easy to
lose: a status-only mapping files a 422 under the generic error, and a
message-only error throws the field list away. The class list must also match
@aivana/sdk's `_classify`, or the same HTTP response is a different exception
depending on which SDK the customer picked.

    python3 -m pytest tests/ -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aivana  # noqa: E402
from aivana.exceptions import from_error_payload  # noqa: E402


def _envelope(code: str, **extra) -> dict:
    return {"error": {"type": code, "code": code, "message": "nope",
                      "request_id": "req_123", **extra}}


CASES = [
    (401, "auth", aivana.AuthError),
    (403, "forbidden", aivana.ForbiddenError),
    (400, "invalid_request", aivana.InvalidRequestError),
    (429, "rate_limit_exceeded", aivana.RateLimitError),
    (502, "upstream", aivana.UpstreamError),
]


def test_each_status_maps_to_its_own_class():
    for status, code, cls in CASES:
        err = from_error_payload(_envelope(code), status)
        assert isinstance(err, cls), f"{status} {code} gave {type(err).__name__}"
        assert err.code == code
        assert err.request_id == "req_123"


def test_422_is_an_invalid_request_by_code_not_status():
    """The shape a developer hits most — a bad field, not a bad key.

    422 is in none of the status lists, so only `code` identifies it as the
    caller's to fix rather than a server fault to retry.
    """
    details = [{"loc": ["body", "temperature"], "msg": "less than or equal to 2",
                "type": "less_than_equal"}]
    err = from_error_payload(_envelope("invalid_request", details=details), 422)
    assert isinstance(err, aivana.InvalidRequestError)
    assert err.details == details, "the per-field list must survive"


def test_details_is_empty_when_the_api_sends_none():
    assert from_error_payload(_envelope("upstream"), 502).details == []


def test_an_unrecognised_error_still_arrives_as_an_aivana_error():
    """A proxy's own 503, or a code this SDK predates, must not raise a
    KeyError/AttributeError on the way out."""
    err = from_error_payload({}, 503)
    assert isinstance(err, aivana.AivanaError)
    assert err.code == "internal_error"
    assert err.request_id is None
    assert err.details == []


def test_forbidden_is_exported_like_the_node_sdk():
    """@aivana/sdk has thrown ForbiddenError since 0.5.0. Without it here a 403
    lands on the bare AivanaError and `except ForbiddenError` does not compile."""
    assert "ForbiddenError" in aivana.__all__
    assert issubclass(aivana.ForbiddenError, aivana.AivanaError)


def test_streaming_errors_arrive_typed_not_as_response_not_read():
    """The streaming path must raise the same classes as the non-streaming one.

    A streamed response has no body until it is read, and the error envelope is
    in the body — so an unread 401 used to escape as httpx.ResponseNotRead, and
    `except AuthError` around a streaming call caught nothing.

    The bodies here are generators ON PURPOSE. httpx pre-reads a response built
    from bytes (`json=` / `content=b"..."`), which is exactly what hid this bug:
    only a body that arrives in pieces, as it does over a real socket, is unread
    when the SDK sees it.
    """
    import asyncio
    import json

    import httpx

    from aivana import client as c

    body = json.dumps(_envelope("invalid_api_key")).encode()
    headers = {"content-type": "application/json"}

    def sync_body():
        yield body

    async def async_body():
        yield body

    def sync_handler(request):
        return httpx.Response(401, headers=headers, content=sync_body())

    def async_handler(request):
        return httpx.Response(401, headers=headers, content=async_body())

    real_client, real_async = c.httpx.Client, c.httpx.AsyncClient
    c.httpx.Client = lambda **kw: real_client(
        transport=httpx.MockTransport(sync_handler), **kw)
    c.httpx.AsyncClient = lambda **kw: real_async(
        transport=httpx.MockTransport(async_handler), **kw)
    try:
        try:
            list(aivana.generate("hi", stream=True))
            raise AssertionError("expected AuthError")
        except aivana.AuthError as err:
            assert err.code == "invalid_api_key"
            assert err.request_id == "req_123"

        async def consume():
            async for _ in aivana.generate_stream("hi"):
                pass

        try:
            asyncio.run(consume())
            raise AssertionError("expected AuthError")
        except aivana.AuthError as err:
            assert err.code == "invalid_api_key"
    finally:
        c.httpx.Client, c.httpx.AsyncClient = real_client, real_async
