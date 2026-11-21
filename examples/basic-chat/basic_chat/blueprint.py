"""Loads an Agent Kit Blueprint export and turns it into SDK options.

The definition is checked strictly and never corrected: a setting this starter cannot honor stops startup
with a message, instead of being dropped or changed on the way to the API.
"""

from __future__ import annotations

import json
import math
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

DIRECTORY = Path(__file__).resolve().parent.parent
RAW_LIMIT = 256 * 1024
DEFINITION_LIMIT = 64 * 1024
CONVENTIONAL_NAME = "blueprint-definition.json"


class BlueprintError(Exception):
    def __init__(self, message: str):
        super().__init__(f"Blueprint: {message}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BlueprintError(message)


def _closed(value: Any, required: list[str], optional: list[str] | None = None) -> None:
    _require(
        isinstance(value, dict),
        "Use a definition object downloaded from Agent Kit’s Inspect / export panel.",
    )
    _require(
        all(key in value for key in required),
        "Required fields are missing. Export the full definition from Agent Kit again.",
    )
    allowed = [*required, *(optional or [])]
    _require(
        all(key in allowed for key in value),
        "Unrecognized fields. Use the definition JSON, not a saved resource, API request, or custom settings object.",
    )


def _numeric(value: Any, name: str, low: float, high: float, integer: bool = False) -> None:
    # bool is a subclass of int in Python, so True would otherwise pass as 1.
    ok = value is None or (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and low <= value <= high
        and (not integer or isinstance(value, int))
    )
    _require(ok, f"{name} must be null or {'a whole number' if integer else 'a number'} from {low:g} to {high:g}.")


@dataclass(frozen=True)
class CompiledBlueprint:
    """`options` are keyword arguments for the SDK's generate functions. Read-only."""

    options: Mapping[str, Any]
    history: str  # "none" or "session"
    purpose: str  # public descriptive text; the system instructions never leave the server


def compile_blueprint(definition: Any) -> CompiledBlueprint:
    """Compile an Agent Kit definition into documented SDK options. Never coerce or drop a setting."""
    _closed(definition, ["purpose", "configuration", "conversation"], ["knowledge"])
    compact = json.dumps(definition, separators=(",", ":"), ensure_ascii=False)
    _require(len(compact.encode("utf-8")) <= DEFINITION_LIMIT, "The definition exceeds 64 KiB of compact JSON.")
    purpose = definition["purpose"]
    _require(
        isinstance(purpose, str) and purpose.strip() != "" and len(purpose) <= 1000,
        "Purpose must contain 1 to 1,000 characters.",
    )
    _require(
        definition.get("knowledge") is None,
        "Sources / Knowledge are not supported by this starter. Use a blueprint without Sources; no retrieval fallback is made.",
    )
    conversation = definition["conversation"]
    _closed(conversation, ["history"])
    _require(conversation["history"] in ("none", "session"), "Conversation history must be none or session.")
    c = definition["configuration"]
    _closed(c, ["system", "effort", "web_search", "temperature", "top_p", "max_tokens", "stop_sequences", "response_format"])
    _require(isinstance(c["system"], str) and len(c["system"]) <= 8000, "System instructions must be a string of at most 8,000 characters.")
    _require(c["effort"] in ("auto", "low", "medium", "high"), "Effort must be auto, low, medium, or high.")
    _require(isinstance(c["web_search"], bool), "Web Search Allowed must be true or false.")
    _numeric(c["temperature"], "Temperature", 0, 2)
    _numeric(c["top_p"], "Top-P", 0, 1)
    _numeric(c["max_tokens"], "Max Tokens", 1, 32000, integer=True)
    _require(
        c["temperature"] is None or c["top_p"] is None,
        "Temperature and Top-P cannot both be set. Choose one in Agent Kit and export again.",
    )
    stops = c["stop_sequences"]
    _require(
        isinstance(stops, list) and len(stops) <= 4 and all(isinstance(s, str) and s != "" for s in stops),
        "Use at most four non-empty stop sequences.",
    )
    fmt = c["response_format"]
    _closed(fmt, ["type"], ["schema"])
    _require(
        fmt["type"] != "json_schema",
        "JSON Schema (Strict) is not supported by this text chat starter. Choose Text explicitly in Agent Kit and export again; no automatic conversion is made.",
    )
    _require(fmt["type"] == "text" and fmt.get("schema") is None, "Response format must be text with no schema.")

    options: dict[str, Any] = {
        "system": c["system"],
        "effort": c["effort"],
        "web_search": c["web_search"],
        "response_format": MappingProxyType({"type": "text"}),
    }
    for field in ("temperature", "top_p", "max_tokens"):
        if c[field] is not None:
            options[field] = c[field]
    if stops:
        options["stop_sequences"] = tuple(stops)
    # Purpose is descriptive metadata, not an instruction. Do not add it to system or messages.
    return CompiledBlueprint(MappingProxyType(options), conversation["history"], purpose.strip())


def thaw(options: Mapping[str, Any]) -> dict[str, Any]:
    """Fresh, mutable copies of compiled options, in the plain types the SDK expects."""
    out: dict[str, Any] = {}
    for key, value in options.items():
        out[key] = dict(value) if isinstance(value, Mapping) else list(value) if isinstance(value, tuple) else value
    return out


def _reject_constant(name: str) -> Any:
    raise ValueError(name)  # Python's json accepts NaN and Infinity; JSON does not


def load_blueprint(env: Mapping[str, str] | None = None, directory: Path | None = None) -> dict | None:
    """The optional conventional file; an explicitly configured missing file always stops startup."""
    env = os.environ if env is None else env
    configured = (env.get("AIVANA_BLUEPRINT_FILE") or "").strip()
    path = Path(directory or DIRECTORY) / (configured or CONVENTIONAL_NAME)
    path = Path(os.path.abspath(path))
    try:
        # O_NONBLOCK so that opening a named pipe cannot hang startup waiting for a writer.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        if not configured:
            return None
        raise BlueprintError("Cannot open the definition file. Check AIVANA_BLUEPRINT_FILE and file permissions, then restart.") from None
    except OSError:
        raise BlueprintError("Cannot open the definition file. Check AIVANA_BLUEPRINT_FILE and file permissions, then restart.") from None
    try:
        try:
            info = os.fstat(fd)
            _require(stat.S_ISREG(info.st_mode), "The definition path must point to a regular JSON file.")
            _require(info.st_size <= RAW_LIMIT, "The JSON file exceeds 256 KiB. Export a smaller definition.")
            data = b""
            while len(data) <= RAW_LIMIT:
                part = os.read(fd, RAW_LIMIT + 1 - len(data))
                if not part:
                    break
                data += part
            _require(len(data) <= RAW_LIMIT, "The JSON file exceeds 256 KiB. Export a smaller definition.")
        except BlueprintError:
            raise
        except OSError:
            raise BlueprintError("Cannot read the definition file. Check file permissions, then restart.") from None
    finally:
        os.close(fd)
    try:
        text = data.decode("utf-8-sig")  # strict UTF-8; a leading byte order mark is tolerated
    except UnicodeDecodeError:
        raise BlueprintError("The definition file must contain UTF-8 JSON.") from None
    try:
        definition = json.loads(text, parse_constant=_reject_constant)
    except ValueError:
        raise BlueprintError("The file is not valid JSON. Export it again; file contents were not logged.") from None
    compile_blueprint(definition)
    return definition
