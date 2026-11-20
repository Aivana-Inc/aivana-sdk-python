<!-- TARGET: Aivana-Inc/aivana-intelligence-api (no access from our account; fallback: aivana-sdk-python, ask to transfer)
     labels: bug, OSU Developer Platform Team | finding F13 (Medium) -->
# Successful response_format (JSON Schema) answers report usage.output_tokens = 0 and bill input only

Found during external-developer validation (aivana-sdk-python#15). Server-side; the SDK passes `usage` through unchanged.

## What happens
A `response_format={"type": "json_schema", ...}` request that succeeds returns the validated object in `structured`, but `usage.output_tokens` is `0` and `credits` cover the input tokens only. Reproduced in both Oct 5 runs and again on 2026-10-20:

```json
{"request_id": "req_1f3cde5633617a4e22fbbc1f", "finish_reason": "stop",
 "usage": {"input_tokens": 50, "output_tokens": 0, "cached_tokens": 0, "credits": 5e-05},
 "answer": "{\"vendorName\":\"Acme Ltd\",\"total\":1250.0}",
 "structured": {"vendorName": "Acme Ltd", "total": 1250.0}}
```
The answer is about 12 tokens long, so 0 cannot be right. Host: `dev-developers.aivana.ai`.

## Docs say
Docs > Structured Outputs / Parameters describe what is *not* charged (a request refused for its schema, or one that fails with `structured_output_failed`) and that the schema counts toward `input_tokens`. Nothing says a successful structured answer's output is free, and `usage.output_tokens` is documented as the answer's tokens.

## Why it matters
Either output isn't metered for structured answers (revenue loss for Aivana), or it is metered but not reported (developers can't reconcile usage with billing). Usage & Insights would show the same gap.

## Reproduce
```python
import aivana
aivana.set_api_base("https://dev-developers.aivana.ai")   # test key
res = aivana.generate(
    "Vendor: Acme Ltd. Total: 1250.",
    response_format={"type": "json_schema", "schema": {
        "type": "object", "properties": {"vendorName": {"type": "string"}, "total": {"type": "number"}},
        "required": ["vendorName", "total"], "additionalProperties": False}},
    effort="low", max_tokens=80)
print(res.structured, res.usage)   # usage.output_tokens == 0
```
Suite case: `PY-LIV-22` (live).

## Suggested fix
Count and report the output tokens of the structured answer, and check what was actually billed for these request ids.
