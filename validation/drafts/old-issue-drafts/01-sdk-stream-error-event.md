<!-- TARGET: Aivana-Inc/aivana-sdk-python | labels: bug, OSU Developer Platform Team | finding F1 (High) -->
# A failed stream ends silently with a partial answer (error event is yielded as an ordinary chunk)

Found during external-developer validation (#15, part of #14).

## What happens
When the API sends an `error` event in the middle of a stream, `aivana.generate(..., stream=True)` (and `generate_stream`) yields it as an ordinary `StreamChunk` and the iteration simply ends. The loop the SDKs page shows prints a partial answer and exits normally: no exception, nothing to tell the caller the answer is incomplete.

The `aivana` CLI handles this correctly (exit 6, "The text above is incomplete."), because it checks `chunk.event == "error"` itself. Code written from the docs does not.

## Docs say
- AI Studio > Docs > SDKs: "Every failure raises ... a subclass of `AivanaError`."
- The SDK streaming examples (README "Streaming", Docs > Streaming Python tab) iterate `chunk.delta` with no error check.

## Reproduce (aivana 0.3.1)
```python
import aivana, httpx, respx

sse = (b'event: delta\ndata: {"text": "Partial"}\n\n'
       b'event: error\ndata: {"type": "upstream_error", "message": "engine error"}\n\n'
       b'event: done\ndata: {"finish_reason": "error", "usage": {}}\n\n')
aivana.api_key = "ai_test_x"
with respx.mock:
    respx.post("https://api.aivana.ai/v1/generate:stream").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=sse))
    for chunk in aivana.generate("hi", stream=True):   # the documented loop
        print(chunk.delta, end="")
# prints "Partial" and returns normally; expected: an AivanaError (e.g. UpstreamError) after "Partial"
```
Suite case: `PY-STR-07` (offline). CLI counterpart passes: `PY-CLI-45`.

## Suggested fix
Raise the mapped `AivanaError` subclass when an `error` event arrives (after yielding the chunks received so far), using the same type-to-class mapping as HTTP errors: `upstream_error`/`timeout` -> `UpstreamError`, `invalid_request` -> `InvalidRequestError`. If raising is not wanted, the README and Docs streaming examples should at least show the `error` check.

## Environment
aivana 0.3.1 (PyPI), Python 3.14.0, macOS arm64. Validation suite: `validation/` on branch `aaronzheng/python-sdk-validation` (results/matrix.md, run 2026-10-20).
