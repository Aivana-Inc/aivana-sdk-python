"""Every entrypoint must forward every wire field.

This SDK drifted from @aivana/sdk because five entrypoints each repeated the
parameter list in their own signature: `system`, `attachments` and `output_shape`
were added to the API and to the Node SDK, and a Python caller's system prompt was
dropped client-side — the call succeeded and simply had no effect, which is the
worst way for an SDK to be wrong.

These tests fail the moment an entrypoint stops forwarding a field, so the next
API addition cannot repeat that silently.

    python3 -m pytest tests/ -q      (or: python3 tests/test_parity.py)
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aivana  # noqa: E402
from aivana.client import WIRE_FIELDS, _body  # noqa: E402

# One value per wire field, chosen so each lands in the body (falsy values are
# omitted by design, so they cannot prove forwarding).
SAMPLE = {
    "mode": "aivana_mmi",
    "messages": [{"role": "user", "content": "hi"}],
    "system": "You are Acme.",
    "assistant_name": "Acme Copilot",
    "temperature": 0.3,
    "max_tokens": 256,
    "output_shape": "summary",
    "attachments": [{"mime_type": "image/png", "data": "AAA"}],
    "metadata": {"trace": "1"},
    "previous_intent": "tech_comparison",
    "pending_action": "code_fix",
    "continue_": True,
}


def test_body_carries_every_wire_field():
    body = _body("hello", **SAMPLE)
    missing = [f for f in WIRE_FIELDS if f not in body]
    assert not missing, f"_body dropped: {missing}"


def test_every_entrypoint_accepts_every_option():
    """A **options entrypoint forwards anything; an explicit signature does not.

    Checked structurally rather than by calling, so this stays true without a
    live server.
    """
    for fn in (aivana.generate, aivana.generate_async, aivana.generate_stream):
        params = inspect.signature(fn).parameters
        has_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        assert has_kwargs, f"{fn.__name__} cannot forward arbitrary options"


def test_chat_applies_options_to_every_turn():
    chat = aivana.Chat(system="You are Acme.", assistant_name="Acme Copilot")
    sent = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"id": "1", "answer": "ok",
                    "intent": {"name": "general", "confidence": 1.0, "signal": "x"},
                    "models_used": ["aivana-mmi"],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                    "latency_ms": 1}

    class _Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None, json=None):
            # Deep copy: `messages` is the Chat's own live list, and it appends
            # the assistant reply right after this returns. Holding the reference
            # made the assertion read post-call state.
            sent.update(copy.deepcopy(json))
            return _Resp()

    import aivana.client as c
    orig, c.httpx.Client = c.httpx.Client, _Client
    try:
        chat.send("first")
        assert sent.get("system") == "You are Acme.", sent
        assert sent.get("assistant_name") == "Acme Copilot", sent
        sent.clear()
        chat.send("second")
        assert sent.get("system") == "You are Acme.", "options lost on turn 2"
        assert sent["messages"][-1]["content"] == "second"
    finally:
        c.httpx.Client = orig


def test_attachment_accepts_both_spellings():
    b = _body("hi", attachments=[{"mimeType": "image/png", "data": "A"}])
    assert b["attachments"][0]["mime_type"] == "image/png"


def test_system_cap_is_client_side():
    try:
        _body("hi", system="x" * 8001)
    except aivana.InvalidRequestError as e:
        assert e.code == "invalid_request"
    else:
        raise AssertionError("over-long system prompt was not rejected")


def test_generation_params_omitted_when_unset():
    """Absence must stay distinguishable from a chosen value, or the SDK
    permanently shadows the engine's per-intent temperature and token budget."""
    b = _body("hi")
    assert "temperature" not in b and "max_tokens" not in b


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn() if not asyncio.iscoroutinefunction(fn) else asyncio.run(fn())
            print(f"  PASS  {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {fn.__name__} — {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
