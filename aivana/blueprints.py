"""Saved Blueprint invocation. Runtime input only; no retries or Generate fallback."""
from __future__ import annotations

import re
from typing import Any, AsyncIterator, Iterator

import httpx
from pydantic import ValidationError

from aivana import client
from aivana.envelopes import BlueprintGenerateResponse, StreamChunk
from aivana.exceptions import AivanaError, InvalidRequestError, UnsupportedAPIError, from_error_payload

_FIELDS = {
    "prompt", "messages", "attachments", "metadata", "previous_intent",
    "pending_action", "continue_", "assistant_name", "intelligence_trace",
}


def _request(id: str, version: int | str, options: dict) -> tuple[str, dict]:
    if not isinstance(id, str) or not re.fullmatch(r"bp_[A-Za-z0-9_-]+", id):
        raise InvalidRequestError("id must be a Blueprint id starting with bp_.", code="invalid_request")
    if not (version == "latest" or (type(version) is int and 0 < version <= 2**53 - 1)):
        raise InvalidRequestError('version must be a positive safe integer or the explicit string "latest".',
                                  code="invalid_request")
    for key in options:
        if key not in _FIELDS:
            raise InvalidRequestError(f"Blueprint invocation does not accept {key}; saved settings cannot be overridden.",
                                      code="invalid_request")
    body = {("continue" if key == "continue_" else key): value
            for key, value in options.items() if value is not None}
    if "attachments" in body:
        if not isinstance(body["attachments"], list):
            raise InvalidRequestError("attachments must be a list of files.", code="invalid_request")
        # Keep an explicitly empty list, and normalize the same file aliases as Generate.
        body["attachments"] = client._normalize_attachments(body["attachments"]) or []
    return f"/v1/blueprints/{id}/versions/{version}/generate", body


def _check(response: httpx.Response) -> None:
    if response.status_code == 404:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        if not isinstance(error, dict) or error.get("code") != "blueprint_not_found":
            raise UnsupportedAPIError(
                "Blueprint invocation is unsupported by this API. Check the API endpoint and deployment.",
                code="blueprint_invocation_unsupported",
                request_id=error.get("request_id") if isinstance(error, dict) else None,
            )
    client._check(response)


def _reference(data: Any, id: str, version: int | str) -> None:
    ref = data.get("blueprint") if isinstance(data, dict) else None
    if (not isinstance(ref, dict) or ref.get("id") != id or type(ref.get("version")) is not int
            or not 0 < ref["version"] <= 2**53 - 1
            or (version != "latest" and ref["version"] != version)):
        raise AivanaError(
            "The API did not confirm the requested Blueprint and resolved numeric version. Do not automatically retry this run.",
            code="invalid_response",
        )


def _result(response: httpx.Response, id: str, version: int | str) -> BlueprintGenerateResponse:
    data = client._json(response)
    _reference(data, id, version)
    try:
        return BlueprintGenerateResponse(**data)
    except ValidationError:
        raise AivanaError("The API returned an invalid Blueprint response. Do not automatically retry this run.",
                          code="invalid_response") from None


def _terminal(chunk: StreamChunk, id: str, version: int | str) -> bool:
    if chunk.event == "error":
        error = chunk.data.get("error", chunk.data)
        if not isinstance(error, dict):
            raise AivanaError("The API returned an invalid Blueprint stream error; the answer is incomplete.", code="invalid_response")
        raise from_error_payload({"error": error}, 502)
    if chunk.event == "done":
        if chunk.data.get("finish_reason") == "error":
            raise from_error_payload({"error": {"code": "upstream", "message": "Blueprint stream failed; the answer is incomplete."}}, 502)
        _reference(chunk.data, id, version)
        return True
    return False


def _incomplete() -> AivanaError:
    return AivanaError("Blueprint stream ended without a done frame; the answer is incomplete. Do not automatically retry generation.",
                       code="incomplete_stream")


def generate(*, id: str, version: int | str, timeout: float = 240.0,
             **options: Any) -> BlueprintGenerateResponse:
    """Invoke a saved version with runtime input, never with settings overrides."""
    path, body = _request(id, version, options)
    with httpx.Client(timeout=timeout, base_url=client.api_base) as connection:
        response = connection.post(path, headers=client._headers(), json=body)
        _check(response)
        return _result(response, id, version)


async def generate_async(*, id: str, version: int | str, timeout: float = 240.0,
                         **options: Any) -> BlueprintGenerateResponse:
    """Asynchronous counterpart of generate()."""
    path, body = _request(id, version, options)
    async with httpx.AsyncClient(timeout=timeout, base_url=client.api_base) as connection:
        response = await connection.post(path, headers=client._headers(), json=body)
        _check(response)
        return _result(response, id, version)


def stream(*, id: str, version: int | str, timeout: float = 240.0,
           **options: Any) -> Iterator[StreamChunk]:
    """Yield SSE chunks; done.data carries the resolved Blueprint id and version.

    Errors and truncated streams raise. Close the iterator if stopping early;
    use contextlib.closing when the loop may break. No generation is retried.
    """
    path, body = _request(id, version, options)
    with httpx.Client(timeout=timeout, base_url=client.api_base) as connection:
        with connection.stream("POST", path + ":stream", headers=client._headers(), json=body) as response:
            if response.status_code >= 400:
                response.read()
            _check(response)
            try:
                for chunk in client._iter_sse(response.iter_lines()):
                    done = _terminal(chunk, id, version)
                    yield chunk
                    if done:
                        return
            except ValidationError:
                raise AivanaError("The API returned an invalid Blueprint stream frame; the answer is incomplete.",
                                  code="invalid_response") from None
            raise _incomplete()


async def stream_async(*, id: str, version: int | str, timeout: float = 240.0,
                       **options: Any) -> AsyncIterator[StreamChunk]:
    """Async counterpart of stream(); use contextlib.aclosing on early exit."""
    path, body = _request(id, version, options)
    async with httpx.AsyncClient(timeout=timeout, base_url=client.api_base) as connection:
        async with connection.stream("POST", path + ":stream", headers=client._headers(), json=body) as response:
            if response.status_code >= 400:
                await response.aread()
            _check(response)
            try:
                async for chunk in client._aiter_sse(response.aiter_lines()):
                    done = _terminal(chunk, id, version)
                    yield chunk
                    if done:
                        return
            except ValidationError:
                raise AivanaError("The API returned an invalid Blueprint stream frame; the answer is incomplete.",
                                  code="invalid_response") from None
            raise _incomplete()
