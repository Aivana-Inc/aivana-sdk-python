<!-- TARGET: Aivana-Inc/aivana-intelligence-api (no access from our account; fallback: aivana-sdk-python, ask to transfer)
     labels: bug, OSU Developer Platform Team | finding F11 (Medium) -->
# max_tokens is not enforced as a ceiling: answers exceed it and report finish_reason "stop"

Found during external-developer validation (aivana-sdk-python#15). Server-side; the SDK sends `max_tokens` correctly (`PY-GEN-03`).

## What happens
With `max_tokens=40` the API returns, and bills, more than 40 output tokens, with `finish_reason="stop"` rather than `"length"`. It is intermittent:

| Run | output_tokens (max_tokens=40) | finish_reason | request id |
|---|---|---|---|
| 2026-10-05 run 1 | 67 | stop | in Oct 5 evidence |
| 2026-10-05 run 2 | 64 | stop | in Oct 5 evidence |
| 2026-10-20 run 2 | 44 | stop | `req_22554beb97b66aec9e616210` |
| 2026-10-20 run 2b | 27 | stop | `req_7470c424240a85311ded3bcc` |
| 2026-10-20 final | **57** | stop | `req_17cb14c01671d3bb49a952a0` |

Prompt: `"Explain TCP vs UDP in detail."`, `effort="low"`, dev host `dev-developers.aivana.ai`.

## Docs say
- Docs > Parameters: "max_tokens: A ceiling on answer length. It can shorten an answer, never lengthen it."
- README: "`max_tokens` is a ceiling, not a target. It can only shorten an answer."
- The CLI prints "the answer was cut off at the length limit" only when `finish_reason == "length"`, so an over-long answer is never flagged.

## Why it matters
A developer budgeting cost with `max_tokens` is billed for tokens past the cap, and cannot detect it from `finish_reason`.

## Suggested fix
Enforce the cap on the final answer (truncate at `max_tokens` and report `length`), or, if multi-model synthesis makes a hard cap impractical, document `max_tokens` as a target and stop calling it a ceiling.

Suite case: `PY-LIV-11` (live; allows +5 tokens for tokenizer differences, so the 44-token run counts as passing).
