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
class RateLimitError(AivanaError): ...
class UpstreamError(AivanaError): ...


def from_error_payload(payload: dict, http_status: int) -> AivanaError:
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
    # A schema the API refuses, and a strict schema asked to stream, are the
    # caller's request to fix like any other 422; they carry codes of their own so
    # a caller can tell them apart (`.code`), and are the same class so one
    # `except InvalidRequestError` covers every request mistake.
    if (http_status == 400 or code in ("invalid_request", "invalid_response_schema",
                                       "structured_output_streaming_not_supported")):
        return InvalidRequestError(msg, code, rid, details)
    if http_status == 429 or code == "rate_limit_exceeded":
        return RateLimitError(msg, code, rid, details)
    if http_status == 502 or code == "upstream":
        return UpstreamError(msg, code, rid, details)
    return AivanaError(msg, code, rid, details)
