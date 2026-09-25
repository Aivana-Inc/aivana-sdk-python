"""Transport hardening: where the API key may go, and what a misbehaving server can
and cannot make the SDK do. Mirrors test/security.test.mjs in @aivana/sdk.

    python3 -m pytest tests/ -q
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aivana  # noqa: E402
from aivana import cli  # noqa: E402
from aivana import client as sdk  # noqa: E402


@pytest.fixture
def transport(monkeypatch):
    """Route every httpx client the SDK opens through one handler."""
    seen: list[httpx.Request] = []
    state: dict = {}

    def install(handler):
        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)
        mock = httpx.MockTransport(record)
        real_sync, real_async = httpx.Client, httpx.AsyncClient
        monkeypatch.setattr(httpx, "Client", lambda *a, **k: real_sync(*a, transport=mock, **k))
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real_async(*a, transport=mock, **k))
        state["seen"] = seen
        return seen

    monkeypatch.setattr(sdk, "api_key", "ai_live_secret")
    monkeypatch.setattr(sdk, "api_base", "https://api.example")
    return install


def _redirect(request: httpx.Request) -> httpx.Response:
    return httpx.Response(307, headers={"location": "https://evil.example/steal"})


def test_a_redirect_is_reported_and_never_followed(transport):
    seen = transport(_redirect)

    async def stream():
        async for _ in aivana.generate_stream("hi"):
            pass

    calls = [
        lambda: aivana.generate("hi"),
        lambda: list(aivana.generate("hi", stream=True)),
        lambda: asyncio.run(aivana.generate_async("hi")),
        lambda: asyncio.run(stream()),
        lambda: aivana.Chat().send("hi"),
    ]
    for call in calls:
        with pytest.raises(aivana.AivanaError) as exc:
            call()
        assert exc.value.code == "redirect"
        assert "HTTP 307" in exc.value.message
    assert {r.url.host for r in seen} == {"api.example"}, "the redirect target must never be contacted"


def test_a_200_that_is_not_json_is_an_aivana_error(transport):
    transport(lambda r: httpx.Response(200, text="<html>proxy login</html>"))
    with pytest.raises(aivana.AivanaError) as exc:
        aivana.generate("hi")
    assert exc.value.code == "invalid_response"


def test_terminal_safe_keeps_text_tab_and_newline_and_drops_every_other_control():
    assert cli._terminal_safe("a\tb\nc") == "a\tb\nc"
    assert cli._terminal_safe("é ü 中文 🙂") == "é ü 中文 🙂"
    assert cli._terminal_safe("\x1b]0;t\x07\x1b[31mx\r\x9b2J\x7f\x00") == "]0;t[31mx2J"
