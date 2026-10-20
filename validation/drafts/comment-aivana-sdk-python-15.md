## Validation complete: aivana 0.3.1 (Python SDK + CLI)

Run as an external developer on 2026-10-20: macOS arm64, Python 3.14 (installs also checked on 3.10, 3.12, 3.13), team test key on `dev-developers.aivana.ai`. The suite is repeatable (`run_validation.sh`, `install_check.sh`) and writes a matrix with one row per case, plus redacted live evidence.

**Totals: 119 cases: 102 pass, 16 known defects, 1 fixed since Oct 5, 0 unexpected failures.** Install checks: 8/8 pass.

| Area | Cases | Result |
|---|---|---|
| Install: fresh venv on 3.10 / 3.12 / 3.13 / 3.14, 3.9 refused, `pipx`, `uvx` | 8 | all pass |
| SDK offline: config, request building, parsing, streaming, errors, Chat | 40 | 31 pass, 9 known defects |
| SDK live: sync, async, streaming, trace, structured output, Chat, errors, effort | 25 | 19 pass, 5 known defects, 1 fixed |
| CLI offline (installed `aivana` as a real process): options, pipes, `--json`, `--trace`, `--image`, exit codes 0-6, API base | 34 | 33 pass, 1 known defect |
| CLI live: basic, `--json`, `--trace`, pipe, invalid key, `--shape extract`, `--image`, default host | 8 | 7 pass, 1 known defect |
| Docs parity: every Python example on the Docs (16) and README (26) runs against the installed SDK | 12 (one per page, 42 examples) | all pass |

### Acceptance criteria
- [x] Fresh virtual environment install succeeds (pip on 4 Pythons, pipx, uvx).
- [x] Basic sync request is validated (live).
- [x] Async and streaming behavior are validated (live). A failed stream is the exception: F1 below.
- [x] CLI basic / JSON / Trace paths are validated (offline + live).
- [x] Representative errors and exit codes are validated (CLI exit codes 0-6 all correct; SDK gaps documented below).
- [x] Published docs and examples are checked against actual behavior (42 examples, /docs/cli statement by statement).
- [x] Every failed case has reproducible evidence (test ID, request id, repro snippet).
- [x] Substantive defects are documented below with reproductions, test IDs and request ids (kept in this issue rather than opened separately).
- [x] Findings are incorporated into the AI Studio integrated developer journey: Aivana-Inc/aivana-ai-studio#149 (comment).

### Changed since the Oct 5 report (0.3.0)
- 0.3.1 moved the default host to `api.aivana.ai`; the suite follows it.
- **F4 server half fixed:** production 401s now include `request_id`.
- **F2 reframed, High -> Low:** test keys are documented (Docs > API Keys) as accepted only in their own environment, so the 401 on production is by design. What remains is the misleading error text.
- **F12 / F14 narrowed** to documentation questions after checking the Docs wording.
- **New:** F15 (an unparseable 200 crashes the CLI with a traceback), F16 (effort is not a ceiling).
- **Not a defect:** the SDK always sends `"mode": "aivana_mmi"`, a fixed constant the conformance spec expects.

The CLI matches its documentation completely and handles every failure case. It is the most reliable path for the journey demo.

### Findings

| ID | Finding | Severity | Owner | Suite case |
|---|---|---|---|---|
| F1 | A failed stream ends silently with a partial answer | High | SDK | PY-STR-07 |
| F5, F15 | Not every failure raises `AivanaError` (network errors, timeouts, unparseable 200s) | Medium | SDK + CLI | PY-ERR-05/06, PY-CLI-34 |
| F8 | Retrying a failed `Chat.send()` sends the question twice | Medium | SDK | PY-CHT-04 |
| F11 | `max_tokens` is not enforced as a ceiling | Medium | API | PY-LIV-11 |
| F13 | JSON Schema answers report `output_tokens = 0` | Medium | API | PY-LIV-22 |
| F16 | `effort="low"` does not bound intelligence (new) | Medium | API / Docs | PY-LIV-23 |
| F3, F4, F6, F7 | Error classes vs. the retry and support docs | Low | SDK | PY-ERR-03/04/07/08 |
| F2 | Test key on production: misleading error message | Low | API + CLI | PY-LIV-03, PY-CLI-L08 |
| F9, F10, F12, F14 | Docs parity: configure snippet, `top_p`, stream events, extract shape, 3.14 classifier | Low | Docs | PY-CFG-07, PY-LIV-18/34 |

Details and reproductions for each:

<details>
<summary><b>F1: A failed stream ends silently with a partial answer (error event is yielded as an ordinary chunk)</b></summary>

#### What happens
When the API sends an `error` event in the middle of a stream, `aivana.generate(..., stream=True)` (and `generate_stream`) yields it as an ordinary `StreamChunk` and the iteration simply ends. The loop the SDKs page shows prints a partial answer and exits normally: no exception, nothing to tell the caller the answer is incomplete.

The `aivana` CLI handles this correctly (exit 6, "The text above is incomplete."), because it checks `chunk.event == "error"` itself. Code written from the docs does not.

#### Docs say
- AI Studio > Docs > SDKs: "Every failure raises ... a subclass of `AivanaError`."
- The SDK streaming examples (README "Streaming", Docs > Streaming Python tab) iterate `chunk.delta` with no error check.

#### Reproduce (aivana 0.3.1)
```python
import aivana, httpx, respx

sse = (b'event: delta\ndata: {"text": "Partial"}\n\n'
       b'event: error\ndata: {"type": "upstream_error", "message": "engine error"}\n\n'
       b'event: done\ndata: {"finish_reason": "error", "usage": {}}\n\n')
aivana.api_key = "ai_test_x"
with respx.mock:
    respx.post("https://api.aivana.ai/v1/generate:stream").mock(
        return_value=httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=sse))
    for chunk in aivana.generate("hi", stream=True):   # the documented loop
        print(chunk.delta, end="")
# prints "Partial" and returns normally; expected: an AivanaError (e.g. UpstreamError) after "Partial"
```
Suite case: `PY-STR-07` (offline). CLI counterpart passes: `PY-CLI-45`.

#### Suggested fix
Raise the mapped `AivanaError` subclass when an `error` event arrives (after yielding the chunks received so far), using the same type-to-class mapping as HTTP errors: `upstream_error`/`timeout` -> `UpstreamError`, `invalid_request` -> `InvalidRequestError`. If raising is not wanted, the README and Docs streaming examples should at least show the `error` check.

#### Environment
aivana 0.3.1 (PyPI), Python 3.14.0, macOS arm64. Validation suite: `validation/` on branch `aaronzheng/python-sdk-validation` (results/matrix.md, run 2026-10-20).

</details>

<details>
<summary><b>F5, F15: Not every failure raises AivanaError: network errors, timeouts and unparseable 200s escape as httpx / pydantic exceptions</b></summary>

#### What happens
Code written to the docs (`except AivanaError:`) misses three kinds of failure:

| Failure | What is raised | Suite case |
|---|---|---|
| Connection refused / DNS failure | `httpx.ConnectError` | `PY-ERR-05` |
| Read timeout | `httpx.ReadTimeout` | `PY-ERR-06` |
| A 200 body missing a required field (e.g. `intent`) | `pydantic_core.ValidationError` | `PY-CLI-34` |

The first two are exactly the failures the docs say are safe to retry, so a retry loop written from the docs crashes on them instead.

For the third, the `aivana` CLI has no handler either: `aivana "..." --json` against such a response prints a raw Python traceback (exit 1) instead of an `aivana: error:` line. Today's API always sends `intent`, so this one is hardening (a field the server drops or renames later would crash every caller).

#### Docs say
AI Studio > Docs > SDKs: "Every failure raises ... a subclass of `AivanaError`."

#### Reproduce (aivana 0.3.1)
```python
import aivana
aivana.api_key = "ai_test_x"
aivana.set_api_base("http://127.0.0.1:9")        # nothing listening
try:
    aivana.generate("hi")
except aivana.AivanaError:
    print("caught as documented")
# -> httpx.ConnectError propagates; the except clause never runs
```

#### Suggested fix
- Wrap `httpx.TransportError` (and its `TimeoutException` subclass) in an `AivanaError` subclass, for example a `ConnectionError`/`TimeoutError` pair or `code="network"` / `code="timeout"`, ideally retryable alongside `UpstreamError`.
- Wrap response-model validation failures in `AivanaError` (for example `code="invalid_response"`, keeping `request_id`), so the CLI prints a one-line error and SDK callers can catch it.

#### Environment
aivana 0.3.1 (PyPI), Python 3.14.0, macOS arm64. Validation suite run 2026-10-20.

</details>

<details>
<summary><b>F3, F4, F6, F7: Error classes don't support the documented retry and support guidance (504/5xx, Retry-After, 422, X-Request-Id)</b></summary>

Four small gaps in how HTTP errors become exception classes. Each has an offline test in the validation suite.

| # | What happens | Docs say | Suite case |
|---|---|---|---|
| F7 | Only 502 maps to `UpstreamError`. 504, 500, 503 and 413 become the base `AivanaError`, so the documented `except (RateLimitError, UpstreamError)` retry never catches a 504. | Docs > Errors & Retries: 504 "The request took too long." -> "Retry..."; the same page's Python example retries with `except (RateLimitError, UpstreamError)`. | `PY-ERR-08` |
| F6 | `RateLimitError` drops the API's `retry_after_ms` and the `Retry-After` header; there is no attribute to wait on. | Docs > Errors & Retries / Rate Limits: the API sends a `Retry-After` header and `retry_after_ms`; "Wait that long, then send it again." | `PY-ERR-07` |
| F3 | A 422 is `InvalidRequestError` only when its `code` is on a short allowlist; any other 422 is the base `AivanaError`. (Live, `temperature=5` came back as `invalid_request` and was classified correctly, so this is hardening.) | Docs > SDKs: "InvalidRequestError: something in the request is wrong (400 or 422)." | `PY-ERR-03` |
| F4 | `request_id` is read only from the JSON body, never from the `X-Request-Id` header. | Docs > Errors & Retries: "request_id is always present." Docs > SDKs: errors carry "the request id. Quote the request id when you contact support." | `PY-ERR-04` |

Update on F4 (2026-10-20): the production host `api.aivana.ai` now includes `request_id` in its 401 body (`PY-LIV-04` passes, e.g. `req_e99ee04dd04206f9077ae09d`), so the server side is fixed. The header fallback is still missing and would cover any error body that omits it.

#### Suggested fix
- Map 504, and probably every 5xx, to `UpstreamError` (or add a `TimeoutError` subclass that the retry example also catches).
- Add `RateLimitError.retry_after` (seconds, float), read from `retry_after_ms` or the `Retry-After` header.
- Map every 422 to `InvalidRequestError`, keeping `details`.
- Fall back to the `X-Request-Id` response header when the body has no `request_id`.

#### Environment
aivana 0.3.1 (PyPI), Python 3.14.0, macOS arm64. Validation suite run 2026-10-20.

</details>

<details>
<summary><b>F8: Retrying a failed Chat.send() sends the user's question twice</b></summary>

#### What happens
`Chat.send()` appends the user turn to `chat.messages` before making the request. If the request fails (rate limit, timeout, upstream error), the turn stays in the history. The natural retry, calling `send()` again with the same text, then sends the question twice in a row. The extra turn is billed as input every time the conversation continues, and the duplicated turn can change the answer.

#### Reproduce (aivana 0.3.1)
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

#### Suggested fix
Add the user turn only after a successful response, or remove it when the request raises. The second request should then carry exactly one copy of the question.

#### Environment
aivana 0.3.1 (PyPI), Python 3.14.0, macOS arm64. Validation suite run 2026-10-20.

</details>

<details>
<summary><b>F2: A test key on the production API gets "Invalid or expired API key", not the environment mismatch the Docs describe</b></summary>

#### Background
AI Studio > Docs > API Keys says test keys (`ai_test_`) are issued by a pre-production environment, are accepted only there, and "won't work against api.aivana.ai". So refusing one on `https://api.aivana.ai` (the SDK and CLI default since 0.3.1) is by design. The same page tells developers what a refusal means: *"If a request is refused as unauthorized and your key starts with ai_test_, you are most likely sending a key from another environment: use a live key from AI Studio."*

#### What happens
Neither the API nor the CLI says that:

- API (production, 401): `invalid_api_key`, *"Invalid or expired API key. Generate a new key or check its expiry."* (`req_90829f901576ccebdc576ec6`, 2026-10-20)
- CLI, exit 3:
  ```
  aivana: error: Invalid or expired API key. Generate a new key or check its expiry. (request id: req_92366b3a1251757e3e6cecf1)
    Create a new key in AI Studio > API Keys, then run:
      export AIVANA_API_KEY=ai_live_...
  ```

The same key works on `https://dev-developers.aivana.ai` (every other live case in the suite). A developer holding a valid test key is told it is invalid or expired. That is what our team concluded on Sept 29 before we understood the environments.

#### Reproduce
```bash
export AIVANA_API_KEY=ai_test_...      # a valid key from a pre-production environment
unset AIVANA_API_BASE                   # the Docs: "no URL to configure"
aivana "Reply with the single word: ok"; echo "exit $?"
```
Suite cases: `PY-LIV-03` (SDK), `PY-CLI-L08` (CLI).

#### Suggested fix
- API: when the presented key's prefix names another environment (`ai_test_` on production, or `ai_live_` on a pre-production host), return a distinct code (e.g. `key_wrong_environment`) and a message saying so. The prefix is not secret, so this reveals nothing.
- CLI/SDK (works today, no API change needed): on a 401 with an `ai_test_` key and the default base, add the Docs' own hint: "This is a test key; test keys work only in the environment that issued them. Use a live key from AI Studio, or set AIVANA_API_BASE to that environment."
- Docs > Quickstart / Command Line: next to "no URL to configure", link the API Keys page's "Live and test keys" section.

#### Environment
aivana 0.3.1 (PyPI) SDK and CLI, Python 3.14.0, macOS arm64, 2026-10-20.

</details>

<details>
<summary><b>F11: max_tokens is not enforced as a ceiling: answers exceed it and report finish_reason "stop"</b></summary>

Server-side; the SDK sends `max_tokens` correctly (`PY-GEN-03`).

#### What happens
With `max_tokens=40` the API returns, and bills, more than 40 output tokens, with `finish_reason="stop"` rather than `"length"`. It is intermittent:

| Run | output_tokens (max_tokens=40) | finish_reason | request id |
|---|---|---|---|
| 2026-10-05 run 1 | 67 | stop | in Oct 5 evidence |
| 2026-10-05 run 2 | 64 | stop | in Oct 5 evidence |
| 2026-10-20 run 2 | 44 | stop | `req_22554beb97b66aec9e616210` |
| 2026-10-20 run 2b | 27 | stop | `req_7470c424240a85311ded3bcc` |
| 2026-10-20 final | **57** | stop | `req_17cb14c01671d3bb49a952a0` |

Prompt: `"Explain TCP vs UDP in detail."`, `effort="low"`, dev host `dev-developers.aivana.ai`.

#### Docs say
- Docs > Parameters: "max_tokens: A ceiling on answer length. It can shorten an answer, never lengthen it."
- README: "`max_tokens` is a ceiling, not a target. It can only shorten an answer."
- The CLI prints "the answer was cut off at the length limit" only when `finish_reason == "length"`, so an over-long answer is never flagged.

#### Why it matters
A developer budgeting cost with `max_tokens` is billed for tokens past the cap, and cannot detect it from `finish_reason`.

#### Suggested fix
Enforce the cap on the final answer (truncate at `max_tokens` and report `length`), or, if multi-model synthesis makes a hard cap impractical, document `max_tokens` as a target and stop calling it a ceiling.

Suite case: `PY-LIV-11` (live; allows +5 tokens for tokenizer differences, so the 44-token run counts as passing).

</details>

<details>
<summary><b>F13: Successful response_format (JSON Schema) answers report usage.output_tokens = 0 and bill input only</b></summary>

Server-side; the SDK passes `usage` through unchanged.

#### What happens
A `response_format={"type": "json_schema", ...}` request that succeeds returns the validated object in `structured`, but `usage.output_tokens` is `0` and `credits` cover the input tokens only. Reproduced in both Oct 5 runs and again on 2026-10-20:

```json
{"request_id": "req_1f3cde5633617a4e22fbbc1f", "finish_reason": "stop",
 "usage": {"input_tokens": 50, "output_tokens": 0, "cached_tokens": 0, "credits": 5e-05},
 "answer": "{\"vendorName\":\"Acme Ltd\",\"total\":1250.0}",
 "structured": {"vendorName": "Acme Ltd", "total": 1250.0}}
```
The answer is about 12 tokens long, so 0 cannot be right. Host: `dev-developers.aivana.ai`.

#### Docs say
Docs > Structured Outputs / Parameters describe what is *not* charged (a request refused for its schema, or one that fails with `structured_output_failed`) and that the schema counts toward `input_tokens`. Nothing says a successful structured answer's output is free, and `usage.output_tokens` is documented as the answer's tokens.

#### Why it matters
Either output isn't metered for structured answers (revenue loss for Aivana), or it is metered but not reported (developers can't reconcile usage with billing). Usage & Insights would show the same gap.

#### Reproduce
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

#### Suggested fix
Count and report the output tokens of the structured answer, and check what was actually billed for these request ids.

</details>

<details>
<summary><b>F16: effort="low" does not bound intelligence: same level, route and perspectives as effort="high"</b></summary>

The SDK and CLI send `effort` correctly (`PY-GEN-03`, `PY-CLI-12`).

#### What happens
On the dev host, `effort="low"` and `effort="high"` produced identical Intelligence Trace summaries on every question tried. Both decision questions went to the top level, Premium, with 3 perspectives at `effort="low"`:

| Question | effort | intelligence_level | route | perspectives | latency | request id |
|---|---|---|---|---|---|---|
| What's the default port for Postgres? | low | Efficient | Efficient single-model | 1 | 4.6 s | `req_cdaaa2a73db13f0d89f22def` |
| ″ | high | Efficient | Efficient single-model | 1 | 2.2 s | `req_6540457bdf7a1d92c3375af0` |
| Should we enter the EU market in 2027? | low | **Premium** | Multi-model collaboration | **3** | 15.1 s | `req_3f66b584485de8b7c9383656` |
| ″ | high | Premium | Multi-model collaboration | 3 | 18.1 s | `req_aef82553ce00ac27a59c93aa` |
| Should we move billing off Stripe before the Series A? | low | **Premium** | Multi-model collaboration | **3** | 15.1 s | `req_e72fa085c0ca0d4d3ce57b60` |
| ″ | high | Premium | Multi-model collaboration | 3 | 21.6 s | `req_3009bdcf10330980bfc1b955` |

All with `intelligence_trace=True, max_tokens=60`, 2026-10-20, `dev-developers.aivana.ai`. Raw data: `results/run-2026-10-20/effort_probe.json`.

#### Docs say
- Docs > Parameters / README: effort is "a ceiling on how much intelligence Aivana may apply"; "Low sets a lower reasoning ceiling and can reduce latency on simpler tasks".
- Docs > Intelligence Trace: "a lower effort bounds that judgement rather than replacing it." (It also says effort and level are "not a lookup table", but if `low` can still reach Premium, nothing is bounded.)
- README: the Stripe question is the example for `effort="high"`, and a Postgres lookup is the example for `"low"`.

#### Why it matters
Developers choose `low` for latency and predictability. As observed, it changes neither. If this is intended, the docs overstate the control; if not, the ceiling isn't being applied (possibly only on the dev host).

#### Questions for Aivana
1. Is `low` meant to exclude Premium (or multi-model routes)? If yes, this is a bug.
2. Is the dev host configured the same as production for effort handling?

Suite case: `PY-LIV-23` (live; asserts that `effort="low"` keeps the Stripe question below Premium).

</details>

<details>
<summary><b>F9, F10, F12, F14: Docs parity (docs and README fixes, packaging note)</b></summary>

From external-developer validation of `aivana` 0.3.1 (this issue). The suite ran **every Python example** on the Docs pages (16) and in the README as published on PyPI (26) against the installed SDK, and checked the Command Line page against the `aivana` command. **All 42 examples run, and every CLI statement on /docs/cli holds**, including the options list, exit codes, the 3-second stdin wait, `< /dev/null`, `> answer.md` and `pipx`/`uvx`. These are the mismatches left:

- [ ] **F9 - Configure snippet raises `KeyError` without the env var.** Docs > SDKs / Quickstart Python tab: `aivana.api_key = os.environ["AIVANA_API_KEY"]`. With the variable unset this is a `KeyError` before any SDK code runs. The SDK already reads `AIVANA_API_KEY` itself (README: "If neither is set, the SDK uses the AIVANA_API_KEY environment variable"). Suggest dropping the line and saying the variable is read automatically, or using `os.environ.get`. Suite: `PY-CFG-07`.
- [ ] **F10 - `top_p` is undocumented; error lists differ.** `top_p` is accepted by `generate()` (`aivana/client.py`) but appears in neither Docs > Parameters, the SDKs page nor the README options table. The README error list omits `ForbiddenError` (403), which the Docs SDKs page lists. Neither page mentions that errors from `generate(stream=True)` surface only once iteration starts. Suggest one canonical options list and one error list, shared by both.
- [ ] **F14 - Two stream events are undocumented (question, not a break).** Even with `intelligence_trace` off, every stream sends `stage` events ("Selecting the right intelligence", "Reviewing multiple perspectives", "Resolving disagreements") and a `route` event `{"model": "aivana-mmi", "provider": "aivana", "role": "mmi"}`; `done` also carries `model`. The Streaming page's table lists `delta`, `done`, `error`, `trace` and correctly tells integrations to skip unknown events, so nothing breaks. No underlying model or provider names appear (`PY-LIV-35` passes). Suggest documenting `stage` (the CLI already shows it as its progress line) and `route`, and confirming that stage names describing the multi-perspective process are meant to be customer-facing. Reproduced 2026-10-20. Suite: `PY-LIV-34`.
- [ ] **F12 - `output_shape="extract"` fallback shape is undocumented.** Docs > Parameters says "Aivana decides the fields from your prompt, so say which ones you want." When a prompt names no fields, the answer can be prose wrapped as `{"response": "I've noted Invoice INV-204 ..."}` (2026-10-20, `req_ef5060ab4b0facc2457946b9`; Oct 5 run 1 likewise). A prompt that names the fields returned them (`--shape extract --json`, same day). Suggest documenting the `{"response": ...}` fallback and pointing developers who need guaranteed fields to `response_format` (JSON Schema), which returned the schema's fields in every run. Suite: `PY-LIV-18`, `PY-CLI-L06`.
- [ ] **F2 follow-up - Quickstart "no URL to configure".** True for live keys. Suggest linking the API Keys page's "Live and test keys" section from Quickstart, SDKs and Command Line, since a test key fails there with an "invalid or expired" error (F2 above).
- [ ] **Packaging (aivana-sdk-python):** `pyproject.toml` classifiers stop at Python 3.13, but 0.3.1 installs and passes on 3.14 (and on 3.10, 3.12, 3.13). Add `Programming Language :: Python :: 3.14`.

Verified 2026-10-20 against aivana-ai-studio `main` (`src/data/docsData.ts`, `docsPagesV2.ts`) and the aivana 0.3.1 README on PyPI.

</details>

**Note for maintainers:** F11, F13, F16 and the 401 wording in F2 are server-side. `Aivana-Inc/aivana-intelligence-api` isn't visible to our account, so they are recorded here; please move them to the owning repo if useful.
