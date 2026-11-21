"""The shape of a chat request from the page, and the limits on it.

These limits match the page's own (public/conversation.mjs). They exist so a request that cannot be valid
is refused here, before it costs anything, and so one browser cannot send an unbounded amount of text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

MESSAGE_CHARS = 4_000
HISTORY_MESSAGES = 16
CONTEXT_CHARS = 24_000
TURN_CHARS = 16_000
ANSWER_CHARS = 16_000

_STRICT = ConfigDict(extra="forbid", strict=True, populate_by_name=False)


class Turn(BaseModel):
    model_config = _STRICT
    role: Literal["user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def _content(cls, value: str) -> str:
        if not value.strip() or len(value) > TURN_CHARS:
            raise ValueError("content")
        return value


class Context(BaseModel):
    """What the page carries from one turn to the next (the API's follow-up state)."""

    model_config = _STRICT
    previous_intent: str | None = Field(default=None, alias="previousIntent", max_length=256)
    pending_action: str | None = Field(default=None, alias="pendingAction", max_length=8_000)


class Settings(BaseModel):
    """The demo controls in the settings panel. Ignored (and refused) when a Blueprint is loaded."""

    model_config = _STRICT
    effort: Literal["auto", "low", "medium", "high"] | None = None
    web_search: StrictBool | None = Field(default=None, alias="webSearch")
    max_tokens: Literal[400, 800, 1600] | None = Field(default=None, alias="maxTokens")


class ChatRequest(BaseModel):
    model_config = _STRICT
    message: str
    history: list[Turn] = []
    context: Context = Context()
    settings: Settings = Settings()

    @field_validator("message")
    @classmethod
    def _message(cls, value: str) -> str:
        if not value.strip() or len(value) > MESSAGE_CHARS:
            raise ValueError("message")
        return value.strip()

    @model_validator(mode="after")
    def _history(self) -> ChatRequest:
        turns = self.history
        # Complete pairs only, oldest first: user, assistant, user, assistant ...
        if len(turns) > HISTORY_MESSAGES or len(turns) % 2 != 0:
            raise ValueError("history")
        if any(turn.role != ("user" if index % 2 == 0 else "assistant") for index, turn in enumerate(turns)):
            raise ValueError("history")
        if len(self.message) + sum(len(turn.content) for turn in turns) > CONTEXT_CHARS:
            raise ValueError("history")
        return self


MESSAGE_PROBLEM = f"Enter a message of 1 to {MESSAGE_CHARS:,} characters."
SETTINGS_PROBLEM = "Choose supported chat settings."
JSON_PROBLEM = "Send a valid JSON chat request."


def describe_problem(errors: list) -> str:
    """One fixed sentence for whatever was wrong with a request. Never repeats what the person sent."""
    first = errors[0] if errors else {}
    if first.get("type") == "json_invalid":
        return JSON_PROBLEM
    location = tuple(first.get("loc", ()))
    section = location[1] if len(location) > 1 else None
    if section == "settings":
        return SETTINGS_PROBLEM
    if section in ("history", "context"):
        return "Check your message and start a new chat if its history is too large."
    # The message itself, a request that is not an object, or a field the page never sends.
    return MESSAGE_PROBLEM
