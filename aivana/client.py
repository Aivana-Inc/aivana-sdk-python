"""HTTP client. The SDK has zero knowledge of models/providers/modes."""
from __future__ import annotations
import json
from typing import Any, AsyncIterator, Iterator, Optional

import httpx

from aivana.envelopes import GenerateResponse, StreamChunk
from aivana.exceptions import AivanaError, from_error_payload


# Module-level config (Stripe-style)
api_key: Optional[str] = None
api_base: str = "http://localhost:8088"


def set_api_key(key: str) -> None:
    global api_key
    api_key = key


def set_api_base(url: str) -> None:
    global api_base
    api_base = url.rstrip("/")


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if api_key:
        h["X-API-Key"] = api_key
    return h


def _body(
    prompt: Optional[str],
    mode: str,
    temperature: Optional[float],
    metadata: Optional[dict],
    messages: Optional[list[dict]] = None,
    previous_intent: Optional[str] = None,
    pending_action: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> dict:
    body: dict[str, Any] = {"mode": mode}
    if prompt:
        body["prompt"] = prompt
    if messages:
        body["messages"] = messages
    if previous_intent:
        body["previous_intent"] = previous_intent
    if pending_action:
        body["pending_action"] = pending_action
    if metadata:
        body["metadata"] = metadata
    # Generation params are OMITTED unless the caller set one. A client-side
    # default would make "I didn't choose" indistinguishable from "I chose this",
    # permanently shadowing the engine's per-intent temperature and its
    # depth-derived token budget.
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return body


def _check(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            payload = resp.json()
        except Exception:
            payload = {"error": {"message": resp.text or "request failed"}}
        raise from_error_payload(payload, resp.status_code)


def generate(
    prompt: str,
    *,
    mode: str = "aivana_mmi",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    stream: bool = False,
    metadata: Optional[dict] = None,
    timeout: float = 120.0,
    previous_intent: Optional[str] = None,
    pending_action: Optional[str] = None,
) -> GenerateResponse | Iterator[StreamChunk]:
    """Sync generate. Returns GenerateResponse, or an iterator of StreamChunk if stream=True.

    Multi-turn without `Chat`: pass `previous_intent` (from `resp.intent.name`)
    and `pending_action` (from `resp.pending_action`) on each follow-up call.
    The server uses them to resolve bare yes/no replies after an offer like
    "Want me to apply these fixes?" to the correct next intent.
    """
    if stream:
        return _sync_stream(prompt, mode, temperature, metadata, timeout,
                            previous_intent=previous_intent, pending_action=pending_action,
                            max_tokens=max_tokens)

    with httpx.Client(timeout=timeout, base_url=api_base) as client:
        resp = client.post(
            "/v1/generate",
            headers=_headers(),
            json=_body(prompt, mode, temperature, metadata,
                       previous_intent=previous_intent, pending_action=pending_action,
                       max_tokens=max_tokens),
        )
        _check(resp)
        return GenerateResponse(**resp.json())


class Chat:
    """Stateful multi-turn helper.

    Usage:
        chat = aivana.Chat()
        print(chat.send("Should we use SQL or NoSQL?").answer)
        print(chat.send("Yes, give me an example").answer)
    """

    def __init__(self, *, mode: str = "aivana_mmi", temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None, timeout: float = 120.0):
        self.mode = mode
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.messages: list[dict] = []
        self._last_intent: Optional[str] = None
        self._pending_action: Optional[str] = None

    def send(self, content: str, *, metadata: Optional[dict] = None) -> GenerateResponse:
        self.messages.append({"role": "user", "content": content})
        body = _body(
            prompt=None,
            mode=self.mode,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            metadata=metadata,
            messages=self.messages,
            previous_intent=self._last_intent,
            pending_action=self._pending_action,
        )
        with httpx.Client(timeout=self.timeout, base_url=api_base) as client:
            resp = client.post("/v1/generate", headers=_headers(), json=body)
            _check(resp)
        result = GenerateResponse(**resp.json())
        self.messages.append({"role": "assistant", "content": result.answer})
        self._last_intent = result.intent.name if result.intent else None
        # Carry forward only the most recent offer. If this turn didn't make
        # one, the contract is cleared on the next request.
        self._pending_action = result.pending_action
        return result

    def reset(self) -> None:
        self.messages = []
        self._last_intent = None
        self._pending_action = None


def _sync_stream(
    prompt: str, mode: str, temperature: Optional[float], metadata: Optional[dict], timeout: float,
    *,
    previous_intent: Optional[str] = None,
    pending_action: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> Iterator[StreamChunk]:
    body = _body(prompt, mode, temperature, metadata,
                 previous_intent=previous_intent, pending_action=pending_action,
                       max_tokens=max_tokens)
    with httpx.Client(timeout=timeout, base_url=api_base) as client:
        with client.stream("POST", "/v1/generate:stream", headers=_headers(), json=body) as resp:
            _check(resp)
            for chunk in _iter_sse(resp.iter_lines()):
                yield chunk


async def generate_async(
    prompt: str,
    *,
    mode: str = "aivana_mmi",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    metadata: Optional[dict] = None,
    timeout: float = 120.0,
    previous_intent: Optional[str] = None,
    pending_action: Optional[str] = None,
) -> GenerateResponse:
    async with httpx.AsyncClient(timeout=timeout, base_url=api_base) as client:
        resp = await client.post(
            "/v1/generate",
            headers=_headers(),
            json=_body(prompt, mode, temperature, metadata,
                       previous_intent=previous_intent, pending_action=pending_action,
                       max_tokens=max_tokens),
        )
        _check(resp)
        return GenerateResponse(**resp.json())


async def generate_stream(
    prompt: str,
    *,
    mode: str = "aivana_mmi",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    metadata: Optional[dict] = None,
    timeout: float = 120.0,
    previous_intent: Optional[str] = None,
    pending_action: Optional[str] = None,
) -> AsyncIterator[StreamChunk]:
    body = _body(prompt, mode, temperature, metadata,
                 previous_intent=previous_intent, pending_action=pending_action,
                       max_tokens=max_tokens)
    async with httpx.AsyncClient(timeout=timeout, base_url=api_base) as client:
        async with client.stream("POST", "/v1/generate:stream", headers=_headers(), json=body) as resp:
            _check(resp)
            async for chunk in _aiter_sse(resp.aiter_lines()):
                yield chunk


def _parse_sse(buffered: list[str]) -> Optional[StreamChunk]:
    event = "message"
    data_lines: list[str] = []
    for line in buffered:
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return None
    try:
        data = json.loads("\n".join(data_lines))
    except Exception:
        data = {"raw": "\n".join(data_lines)}
    return StreamChunk(event=event, data=data)


def _iter_sse(lines: Iterator[str]) -> Iterator[StreamChunk]:
    buf: list[str] = []
    for line in lines:
        if line == "":
            chunk = _parse_sse(buf)
            buf = []
            if chunk is not None:
                yield chunk
            continue
        buf.append(line)
    if buf:
        chunk = _parse_sse(buf)
        if chunk is not None:
            yield chunk


async def _aiter_sse(lines: AsyncIterator[str]) -> AsyncIterator[StreamChunk]:
    buf: list[str] = []
    async for line in lines:
        if line == "":
            chunk = _parse_sse(buf)
            buf = []
            if chunk is not None:
                yield chunk
            continue
        buf.append(line)
    if buf:
        chunk = _parse_sse(buf)
        if chunk is not None:
            yield chunk
