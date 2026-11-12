<!-- TARGET: Aivana-Inc/aivana-sdk-python | labels: bug, OSU Developer Platform Team | findings F3, F4 (SDK side), F6, F7 (all Low) -->
# Error classes don't support the documented retry and support guidance (504/5xx, Retry-After, 422, X-Request-Id)

Found during external-developer validation (#15, part of #14). Four small gaps in how HTTP errors become exception classes. Each has an offline test in the validation suite.

| # | What happens | Docs say | Suite case |
|---|---|---|---|
| F7 | Only 502 maps to `UpstreamError`. 504, 500, 503 and 413 become the base `AivanaError`, so the documented `except (RateLimitError, UpstreamError)` retry never catches a 504. | Docs > Errors & Retries: 504 "The request took too long." -> "Retry..."; the same page's Python example retries with `except (RateLimitError, UpstreamError)`. | `PY-ERR-08` |
| F6 | `RateLimitError` drops the API's `retry_after_ms` and the `Retry-After` header; there is no attribute to wait on. | Docs > Errors & Retries / Rate Limits: the API sends a `Retry-After` header and `retry_after_ms`; "Wait that long, then send it again." | `PY-ERR-07` |
| F3 | A 422 is `InvalidRequestError` only when its `code` is on a short allowlist; any other 422 is the base `AivanaError`. (Live, `temperature=5` came back as `invalid_request` and was classified correctly, so this is hardening.) | Docs > SDKs: "InvalidRequestError: something in the request is wrong (400 or 422)." | `PY-ERR-03` |
| F4 | `request_id` is read only from the JSON body, never from the `X-Request-Id` header. | Docs > Errors & Retries: "request_id is always present." Docs > SDKs: errors carry "the request id. Quote the request id when you contact support." | `PY-ERR-04` |

Update on F4 (2026-10-20): the production host `api.aivana.ai` now includes `request_id` in its 401 body (`PY-LIV-04` passes, e.g. `req_e99ee04dd04206f9077ae09d`), so the server side is fixed. The header fallback is still missing and would cover any error body that omits it.

## Suggested fix
- Map 504, and probably every 5xx, to `UpstreamError` (or add a `TimeoutError` subclass that the retry example also catches).
- Add `RateLimitError.retry_after` (seconds, float), read from `retry_after_ms` or the `Retry-After` header.
- Map every 422 to `InvalidRequestError`, keeping `details`.
- Fall back to the `X-Request-Id` response header when the body has no `request_id`.

## Environment
aivana 0.3.1 (PyPI), Python 3.14.0, macOS arm64. Validation suite run 2026-10-20.
