"""Aivana — packaged B2B Intelligence API client.

Quickstart:
    import aivana
    aivana.api_key = "aiv_live_xxx"
    print(aivana.generate("Should we enter the EU market in 2027?").answer)

    for chunk in aivana.generate("Explain CAP theorem", stream=True):
        print(chunk.delta, end="")
"""
from __future__ import annotations

from aivana.client import (
    Chat,
    api_base,
    api_key,
    generate,
    generate_async,
    generate_stream,
    set_api_base,
    set_api_key,
)
from aivana.envelopes import GenerateResponse, StreamChunk
from aivana.exceptions import (
    AivanaError,
    AuthError,
    InvalidRequestError,
    RateLimitError,
    UpstreamError,
)

__all__ = [
    "api_base",
    "api_key",
    "set_api_base",
    "set_api_key",
    "generate",
    "generate_async",
    "generate_stream",
    "Chat",
    "GenerateResponse",
    "StreamChunk",
    "AivanaError",
    "AuthError",
    "RateLimitError",
    "InvalidRequestError",
    "UpstreamError",
]
__version__ = "0.1.0"
