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


class Stage(BaseModel):
    name: str
    ms: int = 0
    info: dict[str, Any] = {}


class GenerateResponse(BaseModel):
    id: str
    object: str = "generation"
    mode: str
    intent: Intent
    output_format: str
    answer: str
    model: str
    provider: str
    models_used: list[str] = []
    usage: Usage = Usage()
    latency_ms: int = 0
    stages: list[Stage] = []
    finish_reason: str = "stop"
    pending_action: Optional[str] = None


class StreamChunk(BaseModel):
    event: str
    data: dict[str, Any] = {}

    @property
    def delta(self) -> str:
        return self.data.get("text", "") if self.event == "delta" else ""
