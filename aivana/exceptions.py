import email.utils
import re
import time


def parse_retry_after(value, now: float | None = None) -> float | None:
    """The seconds a Retry-After says to wait, or None when it does not say.

    It is whole seconds or an HTTP date. Anything else (empty, text, a negative number) is "not
    said", never a wait. Mirrors _parseRetryAfter() in @aivana/sdk."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    try:
        when = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - (time.time() if now is None else now))


class AivanaError(Exception):
    def __init__(self, message: str, code: str = "internal_error",
                 request_id: str | None = None, details: list | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.request_id = request_id
        # The API's per-field validation list on a 422: [{"loc", "msg", "type"}].
        # It is the only part of the error that says WHICH field is wrong, so it
        # is kept rather than collapsed into the one-line message. Empty for every
        # other error.
        self.details = details or []


class AuthError(AivanaError): ...
class ForbiddenError(AivanaError): ...
class InvalidRequestError(AivanaError): ...
class RateLimitError(AivanaError):
    """A rate limit or quota (429). `retry_after` is the seconds the API said to wait (its
    Retry-After), or None when it did not say. Several developers behind one office or campus
    network share the API's per-address allowance, so this is when it frees up."""

    def __init__(self, message: str, code: str = "internal_error",
                 request_id: str | None = None, details: list | None = None,
                 retry_after: float | None = None):
        super().__init__(message, code, request_id, details)
        self.retry_after = retry_after

class UpstreamError(AivanaError): ...
class UnsupportedAPIError(AivanaError): ...


def from_error_payload(payload: dict, http_status: int,
                       retry_after: float | None = None) -> AivanaError:
    err = payload.get("error", {}) if isinstance(payload, dict) else {}
    code = err.get("code", "internal_error")
    msg = err.get("message", "request failed")
    rid = err.get("request_id")
    details = err.get("details") or []
    # Match on the code first and the status second: the API answers a schema
    # violation with 422, not 400, and only `code` identifies it as the caller's
    # to fix. Mirrors _classify() in @aivana/sdk, class for class.
    if http_status == 401 or code == "auth":
        return AuthError(msg, code, rid, details)
    if http_status == 403 or code == "forbidden":
        return ForbiddenError(msg, code, rid, details)
    # A schema the API refuses, a strict schema asked to stream, and one asked of an
    # environment that does not serve it (`response_format_not_available`: nothing is
    # wrong with the schema) are the
    # caller's request to fix like any other 422; they carry codes of their own so
    # a caller can tell them apart (`.code`), and are the same class so one
    # `except InvalidRequestError` covers every request mistake.
    if (http_status == 400 or code in ("invalid_request", "invalid_response_schema",
                                       "response_format_not_available",
                                       "structured_output_streaming_not_supported")):
        return InvalidRequestError(msg, code, rid, details)
    if http_status == 429 or code == "rate_limit_exceeded":
        # The header is the API's own word; the body's retry_after_ms is the fallback for
        # routes that put it there instead.
        wait = retry_after
        ms = err.get("retry_after_ms")
        if wait is None and isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms >= 0:
            wait = ms / 1000
        return RateLimitError(msg, code, rid, details, retry_after=wait)
    if http_status == 502 or code == "upstream":
        return UpstreamError(msg, code, rid, details)
    return AivanaError(msg, code, rid, details)
