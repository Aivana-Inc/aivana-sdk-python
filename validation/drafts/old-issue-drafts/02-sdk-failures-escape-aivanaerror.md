<!-- TARGET: Aivana-Inc/aivana-sdk-python | labels: bug, OSU Developer Platform Team | findings F5 (Medium), F17 (Low) -->
# Not every failure raises AivanaError: network errors, timeouts and unparseable 200s escape as httpx / pydantic exceptions

Found during external-developer validation (#15, part of #14).

## What happens
Code written to the docs (`except AivanaError:`) misses three kinds of failure:

| Failure | What is raised | Suite case |
|---|---|---|
| Connection refused / DNS failure | `httpx.ConnectError` | `PY-ERR-05` |
| Read timeout | `httpx.ReadTimeout` | `PY-ERR-06` |
| A 200 body missing a required field (e.g. `intent`) | `pydantic_core.ValidationError` | `PY-CLI-34` |

The first two are exactly the failures the docs say are safe to retry, so a retry loop written from the docs crashes on them instead.

For the third, the `aivana` CLI has no handler either: `aivana "..." --json` against such a response prints a raw Python traceback (exit 1) instead of an `aivana: error:` line. Today's API always sends `intent`, so this one is hardening (a field the server drops or renames later would crash every caller).

## Docs say
AI Studio > Docs > SDKs: "Every failure raises ... a subclass of `AivanaError`."

## Reproduce (aivana 0.3.1)
```python
import aivana
aivana.api_key = "ai_test_x"
aivana.set_api_base("http://127.0.0.1:9")        # nothing listening
try:
    aivana.generate("hi")
except aivana.AivanaError:
    print("caught as documented")
# -> httpx.ConnectError propagates; the except clause never runs
```

## Suggested fix
- Wrap `httpx.TransportError` (and its `TimeoutException` subclass) in an `AivanaError` subclass, for example a `ConnectionError`/`TimeoutError` pair or `code="network"` / `code="timeout"`, ideally retryable alongside `UpstreamError`.
- Wrap response-model validation failures in `AivanaError` (for example `code="invalid_response"`, keeping `request_id`), so the CLI prints a one-line error and SDK callers can catch it.

## Environment
aivana 0.3.1 (PyPI), Python 3.14.0, macOS arm64. Validation suite run 2026-10-20.
