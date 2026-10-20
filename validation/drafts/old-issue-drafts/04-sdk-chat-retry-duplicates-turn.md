<!-- TARGET: Aivana-Inc/aivana-sdk-python | labels: bug, OSU Developer Platform Team | finding F8 (Medium) -->
# Retrying a failed Chat.send() sends the user's question twice

Found during external-developer validation (#15, part of #14).

## What happens
`Chat.send()` appends the user turn to `chat.messages` before making the request. If the request fails (rate limit, timeout, upstream error), the turn stays in the history. The natural retry, calling `send()` again with the same text, then sends the question twice in a row. The extra turn is billed as input every time the conversation continues, and the duplicated turn can change the answer.

## Reproduce (aivana 0.3.1)
```python
import json, aivana, httpx, respx
ok = {"id": "g", "answer": "A", "intent": {"name": "general", "confidence": 1.0}, "models_used": ["aivana-mmi"],
      "latency_ms": 1, "finish_reason": "stop",
      "usage": {"input_tokens": 1, "output_tokens": 1, "cached_tokens": 0, "credits": 0}}
aivana.api_key = "ai_test_x"
chat = aivana.Chat()
with respx.mock:
    route = respx.post("https://api.aivana.ai/v1/generate").mock(side_effect=[
        httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "slow down"}}),
        httpx.Response(200, json=ok)])
    try:
        chat.send("What changed in Q3?")
    except aivana.RateLimitError:
        chat.send("What changed in Q3?")             # the natural retry
    print([m["role"] for m in chat.messages])
    print([m["content"] for m in json.loads(route.calls[1].request.content)["messages"]])
# ['user', 'user', 'assistant']                       expected ['user', 'assistant']
# ['What changed in Q3?', 'What changed in Q3?']      the retry sends the question twice
```
Suite case: `PY-CHT-04` (offline).

## Suggested fix
Add the user turn only after a successful response, or remove it when the request raises. The second request should then carry exactly one copy of the question.

## Environment
aivana 0.3.1 (PyPI), Python 3.14.0, macOS arm64. Validation suite run 2026-10-20.
