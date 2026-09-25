"""Aivana — packaged B2B Intelligence API client.

Quickstart:
    import aivana
    aivana.api_key = "ai_live_xxx"          # or aivana.set_api_key(...)
    print(aivana.generate("Should we enter the EU market in 2027?").answer)

    for chunk in aivana.generate("Explain CAP theorem", stream=True):
        print(chunk.delta, end="")
"""
from __future__ import annotations

import sys as _sys
from types import ModuleType as _ModuleType

from aivana import client as _client
from aivana.client import (
    Chat,
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
    ForbiddenError,
    InvalidRequestError,
    RateLimitError,
    UpstreamError,
)

# `api_key` and `api_base` are deliberately NOT imported into this namespace.
# `from aivana.client import api_key` binds a COPY of the value at import time, so
# the name would go stale the moment anything changed it — and, worse, assigning
# to it would bind a new package attribute while the client kept reading its own.
# `aivana.api_key = "..."` looked like it worked, sent no X-API-Key header, and
# failed with a 401 the caller had no way to explain. Module-level config is the
# documented interface (Stripe-style), so reads go through __getattr__ below and
# writes through _Config.__setattr__ — both straight to the client module.
_CONFIG = ("api_key", "api_base")


def __getattr__(name: str):
    """Read config off the client module, never off a stale copy."""
    if name in _CONFIG:
        return getattr(_client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _Config(_ModuleType):
    def __setattr__(self, name, value):
        if name in _CONFIG:
            # Route through the setters so `api_base` gets the same trailing-slash
            # normalisation whichever way it is set.
            if name == "api_key":
                _client.api_key = value
            else:
                _client.set_api_base(value)
            return
        super().__setattr__(name, value)


_sys.modules[__name__].__class__ = _Config

try:                                    # single source of truth: package metadata
    from importlib.metadata import version as _version

    __version__ = _version("aivana")
except Exception:                       # running from a source checkout
    __version__ = "0.0.0+local"

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
    "ForbiddenError",
    "RateLimitError",
    "InvalidRequestError",
    "UpstreamError",
    "__version__",
]
