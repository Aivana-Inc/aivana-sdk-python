"""Both SDKs run the same synthetic Blueprint contract, with no outbound API calls."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

import aivana
from aivana import blueprints

FIXTURE = json.loads((Path(__file__).parents[1] / "conformance/blueprints.json").read_text())
INPUT = {"id": FIXTURE["id"], "version": FIXTURE["version"], "prompt": "hello"}
METHODS = ["generate", "generate_async", "stream", "stream_async"]


def sse(frames):
    return "".join(f"event: {event}\r\ndata: {json.dumps(data, ensure_ascii=False)}\r\n\r\n" for event, data in frames).encode()


def done():
    return ["done", {"finish_reason": "stop", "blueprint": FIXTURE["response"]["blueprint"], "usage": FIXTURE["response"]["usage"]}]


class Bytes(httpx.SyncByteStream, httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content
        self.closed = False

    def __iter__(self):
        for value in self.content:
            yield bytes([value])

    async def __aiter__(self):
        for value in self.content:
            yield bytes([value])

    def close(self):
        self.closed = True

    async def aclose(self):
        self.closed = True


def call(method, options=None):
    options = INPUT if options is None else options
    if method == "generate":
        return blueprints.generate(**options)
    if method == "stream":
        return list(blueprints.stream(**options))

    async def run():
        if method == "generate_async":
            return await blueprints.generate_async(**options)
        return [chunk async for chunk in blueprints.stream_async(**options)]
    return asyncio.run(run())


@pytest.fixture
def stub(monkeypatch):
    real_sync, real_async = httpx.Client, httpx.AsyncClient
    monkeypatch.setattr(aivana.client, "api_base", "https://fixture.invalid")
    monkeypatch.setattr(aivana.client, "api_key", "synthetic-not-a-real-key")

    def setup(responder):
        calls = []

        def handle(request):
            calls.append(request)
            return responder(request)
        transport = httpx.MockTransport(handle)
        monkeypatch.setattr(httpx, "Client", lambda **kw: real_sync(transport=transport, **kw))
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_async(transport=transport, **kw))
        return calls
    return setup


@pytest.mark.parametrize("method", METHODS)
def test_runtime_only_and_auth(stub, method):
    runtime = copy.deepcopy(FIXTURE["input"])
    runtime["continue_"] = runtime.pop("continue")
    runtime["attachments"] = [{"mimeType": "text/csv", "data": "YQox"}]
    stream = Bytes(sse([["delta", {"text": "héllo"}], ["trace", {"status": "completed"}], done()]))
    calls = stub(lambda _: httpx.Response(200, stream=stream) if "stream" in method else httpx.Response(200, json=FIXTURE["response"]))
    result = call(method, {"id": FIXTURE["id"], "version": 3, **runtime})
    assert len(calls) == 1
    assert calls[0].url.path == f"/v1/blueprints/{FIXTURE['id']}/versions/3/generate" + (":stream" if "stream" in method else "")
    assert calls[0].headers["X-API-Key"] == "synthetic-not-a-real-key"
    assert json.loads(calls[0].content) == FIXTURE["input"]
    if "stream" in method:
        assert [chunk.event for chunk in result] == ["delta", "trace", "done"]
        assert result[0].delta == "héllo"
        assert result[-1].data["blueprint"] == FIXTURE["response"]["blueprint"]
        assert stream.closed
    else:
        assert result.blueprint.id == FIXTURE["id"]
        assert result.blueprint.version == 3


@pytest.mark.parametrize("method", METHODS)
def test_latest_explicit(stub, method):
    result = copy.deepcopy(FIXTURE["response"])
    result["blueprint"]["version"] = 7
    calls = stub(lambda _: httpx.Response(200, content=sse([["done", result]])) if "stream" in method else httpx.Response(200, json=result))
    result = call(method, {**INPUT, "version": "latest"})
    assert "/versions/latest/" in calls[0].url.path
    assert (result[-1].data["blueprint"]["version"] if "stream" in method else result.blueprint.version) == 7


@pytest.mark.parametrize("version", [None, 0, -1, 1.5, "3", "Latest", "", True, float("inf"), 2**53])
def test_invalid_version_before_http(stub, version):
    calls = stub(lambda _: pytest.fail("must not fetch"))
    with pytest.raises(aivana.InvalidRequestError):
        call("generate", {**INPUT, "version": version})
    assert calls == []


def test_version_is_required(stub):
    calls = stub(lambda _: pytest.fail("must not fetch"))
    with pytest.raises(TypeError):
        call("generate", {"id": FIXTURE["id"], "prompt": "hi"})
    assert calls == []


@pytest.mark.parametrize("id", [None, "", "bp_", "../v1/generate", "bp_a/versions/latest", "bp_a?x=1"])
def test_invalid_id_before_http(stub, id):
    calls = stub(lambda _: pytest.fail("must not fetch"))
    with pytest.raises(aivana.InvalidRequestError):
        call("generate", {**INPUT, "id": id})
    assert calls == []


@pytest.mark.parametrize("key", ["system", "effort", "web_search", "temperature", "top_p", "max_tokens", "stop_sequences", "response_format", "output_shape", "model", "provider", "knowledge", "blueprint", "mode", "promtp"])
def test_settings_never_silently_dropped(stub, key):
    calls = stub(lambda _: pytest.fail("must not fetch"))
    with pytest.raises(aivana.InvalidRequestError):
        call("generate", {**INPUT, key: None})
    assert calls == []


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("case", FIXTURE["errors"])
def test_errors_one_call_no_fallback(stub, method, case):
    calls = stub(lambda _: httpx.Response(case["status"], stream=Bytes(json.dumps(case["body"]).encode())))
    with pytest.raises(aivana.AivanaError) as caught:
        call(method)
    assert caught.value.code == case["code"]
    if case["code"] == "blueprint_invocation_unsupported":
        assert isinstance(caught.value, aivana.UnsupportedAPIError)
    if case["status"] == 422:
        assert caught.value.details == case["body"]["error"]["details"]
    assert len(calls) == 1
    assert calls[0].url.path.startswith("/v1/blueprints/")


def test_non_json_404(stub):
    calls = stub(lambda _: httpx.Response(404, text="not found"))
    with pytest.raises(aivana.UnsupportedAPIError):
        call("generate")
    assert len(calls) == 1


@pytest.mark.parametrize("method", METHODS)
def test_no_redirect_or_fallback(stub, method):
    calls = stub(lambda _: httpx.Response(307, headers={"location": "https://other.invalid"}))
    with pytest.raises(aivana.AivanaError) as caught:
        call(method)
    assert caught.value.code == "redirect"
    assert len(calls) == 1


@pytest.mark.parametrize("ref", [None, {"id": "bp_other", "version": 3}, {"id": FIXTURE["id"], "version": 4}, {"id": FIXTURE["id"], "version": "3"}, {"id": FIXTURE["id"], "version": True}])
@pytest.mark.parametrize("method", METHODS)
def test_resolved_reference_required(stub, ref, method):
    result = copy.deepcopy(FIXTURE["response"])
    result["blueprint"] = ref
    calls = stub(lambda _: httpx.Response(200, content=sse([["done", result]])) if "stream" in method else httpx.Response(200, json=result))
    with pytest.raises(aivana.AivanaError) as caught:
        call(method)
    assert caught.value.code == "invalid_response"
    assert len(calls) == 1


@pytest.mark.parametrize("method", ["stream", "stream_async"])
@pytest.mark.parametrize("frames,code", [
    ([["delta", {"text": "partial"}]], "incomplete_stream"),
    ([["delta", {"text": "partial"}], ["error", {"code": "upstream", "message": "failed"}]], "upstream"),
    ([["delta", None]], "invalid_response"),
    ([["done", {"finish_reason": "error"}]], "upstream"),
])
def test_incomplete_stream_raises(stub, method, frames, code):
    stream = Bytes(sse(frames))
    calls = stub(lambda _: httpx.Response(200, stream=stream))
    with pytest.raises(aivana.AivanaError) as caught:
        call(method)
    assert caught.value.code == code
    assert len(calls) == 1
    assert stream.closed


def test_sync_iterator_close_releases_transport(stub):
    stream = Bytes(sse([["delta", {"text": "first"}], done()]))
    stub(lambda _: httpx.Response(200, stream=stream))
    iterator = blueprints.stream(**INPUT)
    assert next(iterator).delta == "first"
    iterator.close()
    assert stream.closed


def test_async_iterator_close_releases_transport(stub):
    stream = Bytes(sse([["delta", {"text": "first"}], done()]))
    stub(lambda _: httpx.Response(200, stream=stream))

    async def run():
        iterator = blueprints.stream_async(**INPUT)
        assert (await iterator.__anext__()).delta == "first"
        await iterator.aclose()
    asyncio.run(run())
    assert stream.closed
