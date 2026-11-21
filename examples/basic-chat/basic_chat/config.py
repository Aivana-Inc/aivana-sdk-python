"""Reads and checks the starter's settings (environment variables, usually from a local .env file)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

BLUEPRINT_NAME_MAX = 80
DEFAULT_PORT = 3006


class ConfigError(Exception):
    """A setting is missing or unsafe. The message says which one and never contains a value."""


def parse_blueprint_name(value: str | None) -> str | None:
    """The optional display name for a loaded Blueprint (AIVANA_BLUEPRINT_NAME).

    An Agent Kit export carries a purpose but no name (the name is resource metadata and is deliberately not
    part of the immutable definition), so the person running the starter chooses one here. One plain line;
    it is shown as text, never as markup. Blank means none.
    """
    name = value.strip() if isinstance(value, str) else ""
    if not name:
        return None
    plain = len(name) <= BLUEPRINT_NAME_MAX
    for char in name:
        code = ord(char)
        # No line breaks or control characters.
        if code < 0x20 or 0x7F <= code <= 0x9F or code in (0x2028, 0x2029):
            plain = False
    if not plain:
        raise ConfigError(f"AIVANA_BLUEPRINT_NAME must be a single line of at most {BLUEPRINT_NAME_MAX} characters.")
    return name


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_base: str | None
    port: int
    blueprint_name: str | None

    def __repr__(self) -> str:  # never let the key reach a log or a traceback through repr()
        return f"Settings(port={self.port}, api_base={self.api_base!r}, api_key=<hidden>)"


_PLACEHOLDER_KEY = re.compile(r"^(YOUR_|REPLACE_|ai_live_xxx)", re.IGNORECASE)
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _origin_of(configured: str) -> str:
    """Check AIVANA_API_BASE and return it as a plain origin (scheme://host[:port])."""
    unsafe = ConfigError(
        "AIVANA_API_BASE must be an HTTPS API origin, with no credentials or query string. "
        "Loopback HTTP is allowed for tests."
    )
    try:
        url = urlsplit(configured)
        host, port = url.hostname, url.port  # .port raises ValueError for a malformed port
    except ValueError:
        raise ConfigError("AIVANA_API_BASE must be a valid API URL.") from None
    if not url.scheme or not host:
        raise ConfigError("AIVANA_API_BASE must be a valid API URL.")
    loopback = host in _LOOPBACK
    if url.scheme not in ("https", "http") or (url.scheme == "http" and not loopback):
        raise unsafe
    if url.username or url.password or url.query or url.fragment or url.path not in ("", "/", "/v1", "/v1/"):
        raise unsafe
    shown_host = f"[{host}]" if ":" in host else host
    default_port = 443 if url.scheme == "https" else 80
    return f"{url.scheme}://{shown_host}" + (f":{port}" if port is not None and port != default_port else "")


def read_configuration(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    api_key = (env.get("AIVANA_API_KEY") or "").strip()
    if not api_key or _PLACEHOLDER_KEY.match(api_key):
        raise ConfigError("Set an active AIVANA_API_KEY in the local .env file, then restart.")
    port_text = env.get("PORT") or str(DEFAULT_PORT)
    if not re.fullmatch(r"[0-9]+", port_text) or not 1 <= int(port_text) <= 65535:
        raise ConfigError("PORT must be an integer from 1 to 65535.")
    configured = (env.get("AIVANA_API_BASE") or "").strip()
    return Settings(
        api_key=api_key,
        api_base=_origin_of(configured) if configured else None,
        port=int(port_text),
        blueprint_name=parse_blueprint_name(env.get("AIVANA_BLUEPRINT_NAME")),
    )
