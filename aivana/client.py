"""HTTP client. The SDK has zero knowledge of models/providers/modes."""
from __future__ import annotations
import json
from typing import Any, AsyncIterator, Iterator, Optional

import httpx

from aivana.envelopes import GenerateResponse, StreamChunk
from aivana.exceptions import AivanaError, InvalidRequestError, from_error_payload


# Module-level config (Stripe-style)
api_key: Optional[str] = None
# Production, and the same default as @aivana/sdk's DEFAULT_BASE. It used to point
# at the local engine port, which meant the first call after `pip install aivana`
# was a connection-refused to localhost unless the caller happened to know about
# set_api_base(). Local development is the case that should have to say so, not
# the default.
api_base: str = "https://developers.aivana.ai"


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


def _check(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            payload = resp.json()
        except Exception:
            payload = {"error": {"message": resp.text or "request failed"}}
        raise from_error_payload(payload, resp.status_code)


# Every field the wire accepts, in one place. Five entrypoints used to repeat
# this list in their own signatures, and that is precisely how this SDK drifted
# out of sync with the Node one: `system`, `attachments` and `output_shape` were
# added to the API and to @aivana/sdk, and a Python caller's system prompt was
# silently dropped client-side — the request looked fine and simply had no
# effect. Adding a field here is now the only edit a new API field needs, and
# test_parity.py fails if an entrypoint stops forwarding one.
WIRE_FIELDS = (
    "mode", "prompt", "messages", "system", "assistant_name", "temperature",
    "max_tokens", "output_shape", "attachments", "metadata",
    "previous_intent", "pending_action", "continue", "web_search", "top_p",
    "stop_sequences", "intelligence_trace", "effort",
)

# Mirrors the server's own cap (GenerateRequest.system) and @aivana/sdk's
# client-side check, so an over-long prompt fails the same way in both SDKs
# instead of costing a round trip to learn it.
MAX_SYSTEM_CHARS = 8000


def _normalize_attachments(attachments) -> Optional[list]:
    """Accept `mimeType` or `mime_type`, emit the wire's snake_case.

    @aivana/sdk accepts both spellings, so a team using the two SDKs against one
    backend can move an attachment payload between them unchanged.
    """
    if not attachments:
        return None
    out = []
    for a in attachments:
        if not isinstance(a, dict):
            raise InvalidRequestError("attachment must be a dict with mime_type and data",
                                      code="invalid_request")
        out.append({"mime_type": a.get("mime_type") or a.get("mimeType"),
                    "data": a.get("data")})
    return out


def _body(
    prompt: Optional[str] = None,
    *,
    mode: str = "aivana_mmi",
    messages: Optional[list[dict]] = None,
    system: Optional[str] = None,
    assistant_name: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    output_shape: Optional[str] = None,
    attachments: Optional[list[dict]] = None,
    metadata: Optional[dict] = None,
    previous_intent: Optional[str] = None,
    pending_action: Optional[str] = None,
    continue_: Optional[bool] = None,
    web_search: Optional[bool] = None,
    top_p: Optional[float] = None,
    stop_sequences: Optional[list] = None,
    intelligence_trace: Optional[bool] = None,
    effort: Optional[str] = None,
) -> dict[str, Any]:
    """Build the request body. The single place any field reaches the wire."""
    if system is not None and str(system).strip() and len(str(system)) > MAX_SYSTEM_CHARS:
        raise InvalidRequestError(
            f"system prompt is {len(system)} chars; the maximum is {MAX_SYSTEM_CHARS}. "
            "Keep it to the persona, format and constraints that actually change "
            "the answer.",
            code="invalid_request",
        )

    body: dict[str, Any] = {"mode": mode}
    if prompt:
        body["prompt"] = prompt
    if messages:
        body["messages"] = messages
    if system is not None and str(system).strip():
        body["system"] = str(system)
    if assistant_name:
        body["assistant_name"] = assistant_name
    if output_shape:
        body["output_shape"] = output_shape
    if previous_intent:
        body["previous_intent"] = previous_intent
    if pending_action:
        body["pending_action"] = pending_action
    if metadata:
        body["metadata"] = metadata
    normalized = _normalize_attachments(attachments)
    if normalized:
        body["attachments"] = normalized
    if continue_ is not None:
        body["continue"] = continue_
    # Generation params are OMITTED unless the caller set one. A client-side
    # default would make "I didn't choose" indistinguishable from "I chose this",
    # permanently shadowing the engine's per-intent temperature and its
    # depth-derived token budget.
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    # Web search is THREE-state, so `False` has to reach the wire: it means
    # "never search this request", which is a different instruction from an
    # absent field ("you decide"). Every other option here is skipped when
    # falsy; this one must not be, or every opt-out is silently discarded.
    if web_search is not None:
        body["web_search"] = bool(web_search)
    # `is not None` for the same reason as web_search above, though for a
    # different value: top_p=0.0 is legal and means "always take the single most
    # likely token". A truthiness check would drop the most deterministic setting
    # the parameter has.
    if top_p is not None:
        body["top_p"] = float(top_p)
    if stop_sequences:
        body["stop_sequences"] = [str(x) for x in stop_sequences]
    # Only sent when asked for. An explicit False is still sent: the server treats
    # it the same as omitting, but echoing the caller's own choice back is
    # cheaper to reason about than silently collapsing two different requests.
    if intelligence_trace is not None:
        body["intelligence_trace"] = bool(intelligence_trace)
    # Sent only when the caller picked a band. "auto" is the server default and
    # means "you decide", so sending it changes nothing — but it is forwarded
    # rather than dropped, because a caller who types it explicitly should see
    # it echoed in their own request rather than silently rewritten.
    if effort:
        body["effort"] = str(effort).strip().lower()
    return body


# Keyword options shared by every entrypoint. Documented once; see _body above
# for the full list and the wire names they map to.
_OPTS = """
    system: your own system prompt — persona, tone, format, domain focus. ADDITIVE:
        Aivana keeps its own instructions and they win on conflict, so this shapes an
        answer but cannot change what Aivana discloses about how it was produced.
        Max 8000 chars, checked here before the request is sent.
    assistant_name: the name the assistant presents as ("Acme Copilot"). Renaming is
        all it does — which underlying models answered stays undisclosable.
    temperature / max_tokens: omit to let the engine decide. `max_tokens` is a
        ceiling: it can lower the engine's budget, never raise it.
    top_p: nucleus sampling, 0.0-1.0 — consider only the most likely tokens whose
        probabilities add up to this. It controls randomness the same way
        `temperature` does, by a different mechanism, so set ONE of the two rather
        than both. Omitting it is not the same as 1.0: omitted leaves every model
        on its own default. Where a model cannot accept both, Aivana honours
        `top_p` and drops the temperature for that call.
    web_search: whether to ground this answer in a live web search. THREE states:
        True always searches, False never searches, and OMITTING it lets Aivana
        judge whether the question needs fresh data. Omitted is not the same as
        False. On an API key the default is off, so a search only happens when you
        ask for one.
    intelligence_trace: ask Aivana to explain how it handled this request. Off
        unless you set it. `resp.trace` then carries the ordered steps it went
        through (with timings), a summary of the route it chose, and why — for
        example whether a second independent perspective was engaged, and whether
        live sources were needed. On `stream=True` the same information arrives as
        `trace` events while the answer is being produced. It describes decisions
        and outcomes, never which underlying models answered.
    stop_sequences: up to 4 strings; the answer ends where the first one appears
        and the string itself is not returned. Applied to the answer you receive,
        so it behaves the same on every question — but the text past the marker is
        still generated and still billed, so this shapes output, it does not save
        tokens.
    effort: auto|low|medium|high — how much intelligence to spend on this request.
        `auto` (the default) lets Aivana judge from the question itself. `low` takes
        the fastest, cheapest path; `medium` compares two independent perspectives;
        `high` engages three or more for hard or high-stakes questions. It BOUNDS
        that judgement rather than replacing it, and it is not a length control —
        use `max_tokens` for that. Cost scales roughly with the band.
    output_shape: auto|text|recommendation|summary|tradeoffs|decision|extract.
    attachments: [{"mime_type": "image/png", "data": "<base64 or data: URL>"}] for
        THIS turn only; they are not replayed on later turns.
    messages / previous_intent / pending_action / continue_: multi-turn context.
    metadata: free-form dict echoed into your usage records.
"""


def generate(
    prompt: Optional[str] = None,
    *,
    stream: bool = False,
    timeout: float = 240.0,
    **options: Any,
) -> "GenerateResponse | Iterator[StreamChunk]":
    """Sync generate. Returns GenerateResponse, or an Iterator[StreamChunk] if stream=True.

    Options (all optional):
    """ + _OPTS + """
    Multi-turn without `Chat`: pass `previous_intent` (from `resp.intent.name`) and
    `pending_action` (from `resp.pending_action`) on each follow-up call.
    """
    body = _body(prompt, **options)
    if stream:
        return _sync_stream(body, timeout)
    with httpx.Client(timeout=timeout, base_url=api_base) as client:
        resp = client.post("/v1/generate", headers=_headers(), json=body)
        _check(resp)
        return GenerateResponse(**resp.json())


def _sync_stream(body: dict, timeout: float) -> Iterator[StreamChunk]:
    with httpx.Client(timeout=timeout, base_url=api_base) as client:
        with client.stream("POST", "/v1/generate:stream",
                           headers=_headers(), json=body) as resp:
            _check(resp)
            for chunk in _iter_sse(resp.iter_lines()):
                yield chunk


async def generate_async(
    prompt: Optional[str] = None,
    *,
    timeout: float = 240.0,
    **options: Any,
) -> GenerateResponse:
    """Async generate. Same options as `generate`.
    """ + _OPTS
    async with httpx.AsyncClient(timeout=timeout, base_url=api_base) as client:
        resp = await client.post("/v1/generate", headers=_headers(),
                                 json=_body(prompt, **options))
        _check(resp)
        return GenerateResponse(**resp.json())


async def generate_stream(
    prompt: Optional[str] = None,
    *,
    timeout: float = 240.0,
    **options: Any,
) -> AsyncIterator[StreamChunk]:
    """Async streaming generate. Same options as `generate`.
    """ + _OPTS
    body = _body(prompt, **options)
    async with httpx.AsyncClient(timeout=timeout, base_url=api_base) as client:
        async with client.stream("POST", "/v1/generate:stream",
                                 headers=_headers(), json=body) as resp:
            _check(resp)
            async for chunk in _aiter_sse(resp.aiter_lines()):
                yield chunk


class Chat:
    """Stateful multi-turn helper.

    Every option `generate` accepts may be passed here and is applied to every
    turn — a `system` prompt or `assistant_name` set once holds for the whole
    conversation, matching `aivana.chat({...})` in @aivana/sdk.

        chat = aivana.Chat(system="You are a tax specialist. Answer in bullets.")
        print(chat.send("Should we use SQL or NoSQL?").answer)
        print(chat.send("Yes, give me an example").answer)
    """

    def __init__(self, *, timeout: float = 240.0, **options: Any):
        self.timeout = timeout
        self.options = options
        self.messages: list[dict] = []
        self._last_intent: Optional[str] = None
        self._pending_action: Optional[str] = None

    def send(self, content: str, *, metadata: Optional[dict] = None,
             **overrides: Any) -> GenerateResponse:
        self.messages.append({"role": "user", "content": content})
        opts = {**self.options, **overrides}
        opts.pop("messages", None)          # this turn's history is authoritative
        if metadata is not None:
            opts["metadata"] = metadata
        body = _body(
            None,
            messages=self.messages,
            previous_intent=self._last_intent,
            pending_action=self._pending_action,
            **opts,
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
