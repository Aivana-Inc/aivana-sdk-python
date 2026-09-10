"""Response envelopes — kept identical to the server's own and to @aivana/sdk.

Every field the API returns is declared here and nothing else. The envelope
deliberately carries no description of HOW an answer was produced, and fields of
that kind must not be added back: an earlier version of this file declared
several the API no longer returns, which made every `aivana.generate()` call
raise a pydantic ValidationError before the caller ever saw their answer.

`models_used` carries the Aivana-branded id only.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class Intent(BaseModel):
    name: str
    confidence: float
    signal: str = ""


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    credits: float = 0.0


class GenerateResponse(BaseModel):
    """Mirrors the server's GenerateResponse field for field.

    Every field except `id`, `answer` and `intent` carries a default, so a server
    that adds one does not break older clients — the failure this file caused ran
    the other way, on fields the server DROPPED.
    """

    id: str
    answer: str
    intent: Intent
    # Structured output for `output_shape`: the parsed object, or the parse error
    # when the model returned something unusable.
    structured: Optional[dict[str, Any]] = None
    structured_error: Optional[str] = None
    # Aivana-branded id (e.g. ["aivana-mmi"]) — never the models behind it.
    models_used: list[str] = []
    usage: Usage = Usage()
    latency_ms: int = 0
    finish_reason: str = "stop"
    # If the assistant ended this turn with a yes/no offer, the intent a bare
    # "yes" should resolve to next. Echo it back as `pending_action`.
    pending_action: Optional[str] = None


class StreamChunk(BaseModel):
    event: str
    data: dict[str, Any] = {}

    @property
    def delta(self) -> str:
        return self.data.get("text", "") if self.event == "delta" else ""
