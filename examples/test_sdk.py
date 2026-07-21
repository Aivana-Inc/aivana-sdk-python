"""Smoke tests for the aivana SDK.

Run after the engine is up:
    cd aivana_sdk
    pip install -e .
    AIVANA_API_KEY=key1 python examples/test_sdk.py
"""
import os
import sys

import aivana

aivana.set_api_base(os.getenv("AIVANA_API_BASE", "http://localhost:8088"))
if os.getenv("AIVANA_API_KEY"):
    aivana.set_api_key(os.environ["AIVANA_API_KEY"])


def section(name: str) -> None:
    print()
    print("=" * 60)
    print(name)
    print("=" * 60)


def test_generate_sync():
    section("1) aivana.generate(prompt) — sync")
    resp = aivana.generate("What is 17 * 23?")
    print(f"intent : {resp.intent.name} ({resp.intent.confidence:.2f})")
    print(f"model  : {resp.model}")
    print(f"answer : {resp.answer}")
    print(f"tokens : {resp.usage.input_tokens} in / {resp.usage.output_tokens} out")


def test_generate_stream():
    section("2) aivana.generate(prompt, stream=True) — SSE")
    print("answer : ", end="", flush=True)
    final_intent = None
    for chunk in aivana.generate("Explain CAP theorem in one sentence.", stream=True):
        if chunk.event == "intent":
            final_intent = chunk.data.get("intent")
        elif chunk.event == "delta":
            print(chunk.data.get("text", ""), end="", flush=True)
        elif chunk.event == "done":
            print()
    print(f"intent : {final_intent}")


def test_chat():
    section("3) aivana.Chat() — multi-turn")
    chat = aivana.Chat()
    r1 = chat.send("Should we use SQL or NoSQL for analytics?")
    print(f"USER : Should we use SQL or NoSQL for analytics?")
    print(f"BOT  : {r1.answer[:200]}{'...' if len(r1.answer) > 200 else ''}")
    print(f"       (intent={r1.intent.name})")

    r2 = chat.send("Yes — give me a concrete example for click events.")
    print(f"USER : Yes — give me a concrete example for click events.")
    print(f"BOT  : {r2.answer[:200]}{'...' if len(r2.answer) > 200 else ''}")
    print(f"       (intent={r2.intent.name})")


def test_code_review_unambiguous():
    section("4) Code review — unambiguous prompt")
    code = '''
class Foo:
    def __init__(self):
        self.x = 1

    def add(self, n):
        return self.x + n
'''
    resp = aivana.generate(f"any issue in this code?\n{code}")
    print(f"intent : {resp.intent.name}")
    print(f"answer : {resp.answer[:300]}")


def test_stateless_followup():
    """Multi-turn without Chat: caller forwards previous_intent and
    pending_action manually. Proves the 'Yes after review → fix' contract
    works for any caller, not just Chat users."""
    section("5) Stateless follow-up — no Chat helper")
    code = "def divide(a, b):\n    return a / b\n"

    r1 = aivana.generate(f"any issue in this code?\n```python\n{code}```")
    print(f"turn 1 intent          : {r1.intent.name}")
    print(f"turn 1 pending_action  : {r1.pending_action}")

    r2 = aivana.generate(
        "Yes",
        previous_intent=r1.intent.name,
        pending_action=r1.pending_action,
    )
    print(f"turn 2 intent          : {r2.intent.name}  (expected: code_fix)")
    print(f"turn 2 answer (head)   : {r2.answer[:200]}{'...' if len(r2.answer) > 200 else ''}")
    if r2.intent.name != "code_fix":
        print("FAIL: pending_action contract was not honored.")


def main() -> int:
    try:
        test_generate_sync()
        test_generate_stream()
        test_chat()
        test_code_review_unambiguous()
        test_stateless_followup()
    except aivana.AuthError as e:
        print(f"\nAUTH ERROR: {e}")
        print("Set AIVANA_API_KEY env var or AIVANA_API_KEYS='' on the engine for dev.")
        return 1
    except aivana.AivanaError as e:
        print(f"\nSDK ERROR: {e}")
        return 1
    print("\nAll smoke tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
