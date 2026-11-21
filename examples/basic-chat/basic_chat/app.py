"""The chat server: a FastAPI app with three routes and a fixed set of page files.

    GET  /                      the page and its few files (a fixed list, never a directory listing)
    GET  /api/config            what the page may know about this server's setup
    POST /api/chat              one question, one whole answer
    POST /api/chat/stream       one question, the answer as it is written (one JSON object per line)

The server holds no conversation. The page sends the recent history with every question, so two browser
tabs, or two people, can never see each other's chat.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .blueprint import CompiledBlueprint, compile_blueprint, thaw
from .config import parse_blueprint_name
from .errors import RequestError, envelope, invalid, public_failure
from .guard import BODY_TIMEOUT_S, CHAT_PATHS, RequestGuard
from .models import ANSWER_CHARS, ChatRequest, describe_problem

PUBLIC = Path(__file__).resolve().parent.parent / "public"
TEXT_JS, TEXT_CSS, AVIF = "text/javascript; charset=utf-8", "text/css; charset=utf-8", "image/avif"

# The only files the server will ever send. A request for anything else is a 404, whatever the path looks like.
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", TEXT_JS),
    "/conversation.mjs": ("conversation.mjs", TEXT_JS),
    "/markdown.mjs": ("markdown.mjs", TEXT_JS),
    "/highlight.mjs": ("highlight.mjs", TEXT_JS),
    "/render.mjs": ("render.mjs", TEXT_JS),
    "/typing.mjs": ("typing.mjs", TEXT_JS),
    "/assets/aivana-logo.avif": ("assets/aivana-logo.avif", AVIF),
    "/assets/aivana-sparkle.avif": ("assets/aivana-sparkle.avif", AVIF),
    "/styles.css": ("styles.css", TEXT_CSS),
}

# The page is shared, file for file, with the Node starter. Its footer links to that starter's source; this server
# points the one link at this starter instead, and refuses to start if the page no longer contains it exactly once.
NODE_SOURCE_URL = "https://github.com/Aivana-Inc/aivana-sdk-node/tree/main/examples/basic-chat"
PYTHON_SOURCE_URL = "https://github.com/Aivana-Inc/aivana-sdk-python/tree/main/examples/basic-chat"

DEFAULT_OPTIONS = {"max_tokens": 800, "web_search": False}
INTERRUPTED = "The response was interrupted. It may have used credit, and it was not sent again automatically."


def _load_assets(directory: Path) -> dict[str, tuple[bytes, str]]:
    loaded: dict[str, tuple[bytes, str]] = {}
    for route, (name, media_type) in ASSETS.items():
        data = (directory / name).read_bytes()
        if route == "/":
            page = data.decode("utf-8")
            if page.count(NODE_SOURCE_URL) != 1:
                raise RuntimeError("public/index.html no longer has the source link this server rewrites. Re-sync the page from the Node starter.")
            data = page.replace(NODE_SOURCE_URL, PYTHON_SOURCE_URL).encode("utf-8")
        loaded[route] = (data, media_type)
    return loaded


def _whole_count(value: Any) -> int | None:
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1_000_000_000
    return value if ok else None


def public_usage(usage: Any, latency_ms: Any) -> dict[str, int]:
    """What the page may show about the latest request: token counts and time, and only what the response
    really carried. Never credits or cost."""
    out: dict[str, int] = {}
    usage = usage if isinstance(usage, dict) else {}
    if (count := _whole_count(usage.get("input_tokens"))) is not None:
        out["inputTokens"] = count
    if (count := _whole_count(usage.get("output_tokens"))) is not None:
        out["outputTokens"] = count
    if isinstance(latency_ms, (int, float)) and not isinstance(latency_ms, bool) and math.isfinite(latency_ms) and 0 <= latency_ms <= 3_600_000:
        out["latencyMs"] = math.floor(latency_ms + 0.5)  # round half up, as the page's own figures do
    return out


def _line(event: str, data: dict) -> bytes:
    return json.dumps({"event": event, "data": data}, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


async def _hung_up(request: Request) -> None:
    """Returns when the browser closes its end of the connection."""
    while (await request.receive())["type"] != "http.disconnect":
        pass


def create_app(
    *,
    client: Any,
    blueprint: dict | None = None,
    blueprint_name: str | None = None,
    timeout_s: float = 120.0,
    body_timeout_s: float = BODY_TIMEOUT_S,
    public_dir: Path = PUBLIC,
) -> FastAPI:
    """A stateless chat app. Pass an SDK client (see client.ChatClient) rather than sharing one across browsers."""
    if not (callable(getattr(client, "generate", None)) and callable(getattr(client, "generate_stream", None))):
        raise ValueError("An Aivana SDK client is required.")
    if blueprint is None:
        profile = CompiledBlueprint(DEFAULT_OPTIONS, "session", "")
    else:
        profile = compile_blueprint(blueprint)
    session = profile.history == "session"
    # A loaded Blueprint's public description and its settings are shown read-only; its instructions never are.
    # The name is the local AIVANA_BLUEPRINT_NAME setting (the export has none) and means nothing without a Blueprint.
    name = parse_blueprint_name(blueprint_name) if blueprint is not None else None
    public_config: dict[str, Any] = {
        "blueprintLoaded": blueprint is not None,
        "history": profile.history,
        "webSearch": profile.options["web_search"],
    }
    if blueprint is not None:
        public_config["blueprint"] = {
            **({"name": name} if name else {}),
            "purpose": profile.purpose,
            "effort": profile.options["effort"],
            "maxTokens": profile.options.get("max_tokens"),
        }
    assets = _load_assets(public_dir)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    app.add_middleware(RequestGuard, body_timeout=body_timeout_s)

    # ---- error answers: always our own fixed sentences ------------------------------------------------------------

    @app.exception_handler(RequestError)
    async def request_error(_: Request, error: RequestError):
        return JSONResponse(envelope(error.code, error.message), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError):
        # FastAPI's default answer repeats the rejected input back. This one never does.
        return JSONResponse(envelope("invalid_request", describe_problem(error.errors())), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException):
        if error.status_code == 405 and request.url.path in CHAT_PATHS:
            return JSONResponse(envelope("method_not_allowed", "Use POST for chat."), status_code=405, headers=error.headers)
        # Anything else that is not a route here is simply "not found", whatever method asked.
        return JSONResponse(envelope("not_found", "Not found."), status_code=404)

    # ---- the page and its settings -------------------------------------------------------------------------------

    def serve(data: bytes, media_type: str):
        async def handler() -> Response:
            return Response(data, media_type=media_type)

        return handler

    for route, (data, media_type) in assets.items():
        app.add_api_route(route, serve(data, media_type), methods=["GET"], include_in_schema=False)

    @app.get("/api/config", include_in_schema=False)
    async def config() -> JSONResponse:
        return JSONResponse(public_config)

    # ---- chat ----------------------------------------------------------------------------------------------------

    def sdk_options(body: ChatRequest) -> dict[str, Any]:
        if blueprint is not None and body.settings.model_fields_set:
            raise invalid("Imported Blueprint settings are locked. Remove chat overrides.")
        options = thaw(profile.options)
        if blueprint is None:
            chosen = body.settings
            if chosen.effort is not None:
                options["effort"] = chosen.effort
            if chosen.web_search is not None:
                options["web_search"] = chosen.web_search
            if chosen.max_tokens is not None:
                options["max_tokens"] = chosen.max_tokens
        earlier = [{"role": turn.role, "content": turn.content} for turn in body.history] if session else []
        options["messages"] = [*earlier, {"role": "user", "content": body.message}]
        if session:
            if body.context.previous_intent is not None:
                options["previous_intent"] = body.context.previous_intent
            if body.context.pending_action is not None:
                options["pending_action"] = body.context.pending_action
        return options

    def next_context(intent_name: Any, pending_action: Any) -> dict[str, str]:
        context: dict[str, str] = {}
        if session and isinstance(intent_name, str) and len(intent_name) <= 256:
            context["previousIntent"] = intent_name
        if session and isinstance(pending_action, str) and len(pending_action) <= 8_000:
            context["pendingAction"] = pending_action
        return context

    def failure(error: BaseException | None, timed_out: bool = False) -> JSONResponse:
        status, code, message = public_failure(error, timed_out)
        return JSONResponse(envelope(code, message), status_code=status)

    @app.post("/api/chat", include_in_schema=False)
    async def chat(request: Request, body: ChatRequest) -> Response:
        options = sdk_options(body)
        call = asyncio.ensure_future(client.generate(**options))
        hung_up = asyncio.ensure_future(_hung_up(request))
        try:
            # The browser leaving, or the time running out, stops the call to Aivana. Cancelling it closes the
            # connection, so nothing keeps generating (and costing) for an answer nobody will read.
            await asyncio.wait({call, hung_up}, timeout=timeout_s, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (call, hung_up):
                task.cancel()
            await asyncio.gather(call, hung_up, return_exceptions=True)
        if hung_up.done() and not hung_up.cancelled():
            return Response(status_code=499)
        if call.cancelled():
            return failure(None, timed_out=True)
        try:
            result = call.result()
            answer = result.answer
            if not isinstance(answer, str) or not answer.strip() or len(answer) > ANSWER_CHARS:
                raise ValueError("Invalid answer")
            fields = result.model_fields_set
            usage = result.usage.model_dump(include=result.usage.model_fields_set) if "usage" in fields else None
            latency = result.latency_ms if "latency_ms" in fields else None
            return JSONResponse({
                "answer": answer,
                "context": next_context(result.intent.name, result.pending_action),
                "usage": public_usage(usage, latency),
            })
        except Exception as error:  # noqa: BLE001 - every failure becomes one fixed public answer
            return failure(error)

    @app.post("/api/chat/stream", include_in_schema=False)
    async def chat_stream(body: ChatRequest) -> StreamingResponse:
        options = sdk_options(body)
        return StreamingResponse(
            _stream(client, options, next_context, timeout_s),
            media_type="application/x-ndjson; charset=utf-8",
            headers={"X-Accel-Buffering": "no"},
        )

    return app


_END = object()


async def _stream(client: Any, options: dict[str, Any], next_context, timeout_s: float) -> AsyncIterator[bytes]:
    """Sends each piece of the answer as it arrives, then one `done` (or one `error`) line.

    One task (the producer) owns the SDK's stream from start to finish. When the browser leaves, Starlette cancels
    this generator; its `finally` cancels the producer, which unwinds the SDK's `async with` blocks and closes the
    connection to Aivana. That is what makes Stop work at any moment, even before the first word has arrived.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=32)  # a full queue holds the producer back: no unbounded buffering

    async def produce() -> None:
        try:
            async with contextlib.aclosing(client.generate_stream(**options)) as chunks:
                async for chunk in chunks:
                    await queue.put(chunk)
            await queue.put(_END)
        except Exception as error:  # noqa: BLE001 - handed to the reader, which reports one fixed message
            await queue.put(error)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    producer = asyncio.ensure_future(produce())
    answer, finished, context, usage = "", False, {}, {}
    try:
        while True:
            item = await asyncio.wait_for(queue.get(), max(deadline - loop.time(), 0))
            if item is _END:
                break
            if isinstance(item, BaseException):
                raise item
            data = item.data if isinstance(item.data, dict) else {}
            if item.event == "delta" and isinstance(data.get("text"), str):
                answer += data["text"]
                if len(answer) > ANSWER_CHARS:
                    raise ValueError("Answer exceeded starter limit")
                yield _line("delta", {"text": data["text"]})
            elif item.event == "done":
                finished = True
                usage = public_usage(data.get("usage"), data.get("latency_ms"))
                intent = data.get("intent")
                context = next_context(intent.get("name") if isinstance(intent, dict) else None, data.get("pending_action"))
            elif item.event == "error":
                raise RuntimeError("The upstream stream reported an error")
        if not finished or not answer.strip():
            raise RuntimeError("Incomplete streamed answer")
        yield _line("done", {"context": context, "usage": usage})
    except Exception:  # noqa: BLE001 - a timeout, an upstream failure or a bad stream: one fixed message
        yield _line("error", {"message": INTERRUPTED})
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
