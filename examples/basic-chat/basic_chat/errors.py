"""What the browser is told when something goes wrong.

Every failure answer is `{"error": {"code": ..., "message": ...}}` with a fixed code and a fixed sentence.
Nothing from the SDK, the API or a Python exception is ever copied into one: those can carry request
details or credentials, and the person at the keyboard cannot act on them anyway.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from aivana import AivanaError, AuthError, ForbiddenError, InvalidRequestError, RateLimitError


class RequestError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def invalid(message: str = "Check your message and start a new chat if its history is too large.") -> RequestError:
    return RequestError(400, "invalid_request", message)


def envelope(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def envelope_bytes(code: str, message: str) -> bytes:
    return json.dumps(envelope(code, message), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def public_failure(error: BaseException | None, timed_out: bool = False) -> tuple[int, str, str]:
    """(HTTP status, code, message) for something that went wrong while talking to Aivana."""
    if timed_out or isinstance(error, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        return (504, "timeout", "Aivana did not finish in time. The request may have used credit. Try a shorter message when ready.")
    if isinstance(error, AuthError):
        return (502, "authentication_failed", "Aivana rejected the server's API key. Check .env and restart the app.")
    if isinstance(error, AivanaError) and error.code == "insufficient_credit":
        return (402, "insufficient_credit", "The Aivana account needs more credit. Check Billing in AI Studio.")
    if isinstance(error, ForbiddenError):
        return (403, "access_denied", "This API key cannot make this request. Check its permissions and API environment.")
    if isinstance(error, InvalidRequestError):
        return (400, "invalid_request", "Aivana could not accept this request. Try a shorter message or start a new chat.")
    if isinstance(error, RateLimitError):
        return (429, "rate_limited", "Too many requests. Wait a moment before trying again.")
    return (
        502,
        "unavailable",
        "Aivana could not complete the request. Check your connection and API environment. "
        "If Aivana accepted the request, it was not sent again automatically.",
    )
