class AivanaError(Exception):
    def __init__(self, message: str, code: str = "internal_error", request_id: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.request_id = request_id


class AuthError(AivanaError): ...
class InvalidRequestError(AivanaError): ...
class RateLimitError(AivanaError): ...
class UpstreamError(AivanaError): ...


def from_error_payload(payload: dict, http_status: int) -> AivanaError:
    err = payload.get("error", {}) if isinstance(payload, dict) else {}
    code = err.get("code", "internal_error")
    msg = err.get("message", "request failed")
    rid = err.get("request_id")
    if http_status == 401 or code == "auth":
        return AuthError(msg, code, rid)
    if http_status == 400 or code == "invalid_request":
        return InvalidRequestError(msg, code, rid)
    if http_status == 429 or code == "rate_limit_exceeded":
        return RateLimitError(msg, code, rid)
    if http_status == 502 or code == "upstream":
        return UpstreamError(msg, code, rid)
    return AivanaError(msg, code, rid)
