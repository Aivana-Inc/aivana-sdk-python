"""The one place this starter touches the Aivana SDK.

`ChatClient` is deliberately small so the rest of the app depends on two methods, and tests can swap in a fake.
The SDK keeps its API key and base address in module-level settings, so this wrapper sets them once and a
process runs one key. That suits a local starter; a multi-tenant service would pass a key per request instead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

import aivana


class ChatClient(Protocol):
    async def generate(self, **options: Any) -> Any: ...

    def generate_stream(self, **options: Any) -> AsyncIterator[Any]: ...


class SdkClient:
    """Calls the real SDK, with the `messages` list the page sends (so no prompt text).

    Retries are the SDK's own, and narrow on purpose: it waits and asks again only when Aivana refuses a request
    for a per-minute rate limit (at most twice), which happens before any work or billing. A request Aivana may
    have accepted (a timeout, an error after it started, a dropped connection) is never sent again behind the
    person's back: they decide whether to try again.
    """

    def __init__(self, api_key: str, api_base: str | None = None, timeout: float = 120.0):
        aivana.set_api_key(api_key)
        if api_base:
            aivana.set_api_base(api_base)
        self.timeout = timeout

    async def generate(self, **options: Any) -> Any:
        return await aivana.generate_async(None, timeout=self.timeout, **options)

    def generate_stream(self, **options: Any) -> AsyncIterator[Any]:
        return aivana.generate_stream(None, timeout=self.timeout, **options)
