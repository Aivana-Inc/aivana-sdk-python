## Python SDK / CLI validation: input for the journey (from Aivana-Inc/aivana-sdk-python#15)

Python coverage of the journey's steps 2, 5 and 6, run as an external developer on `aivana` 0.3.1 (PyPI), 2026-10-20. Full matrix and evidence are in the validation suite (`validation/` on branch `aaronzheng/python-sdk-validation` of aivana-sdk-python: `results/matrix.md`, `results/install.md`, `results/evidence.jsonl`).

| Journey step | Expected (Docs) | Actual | Result | Issue |
|---|---|---|---|---|
| 2. Use an approved API key | Quickstart: "no URL to configure" | Not tested with a live key (the team has only a test key). Our approved **test** key is refused on the default `api.aivana.ai` (by design per Docs > API Keys), but the 401 says "Invalid or expired API key. Generate a new key" and the CLI suggests `ai_live_...`. With `AIVANA_API_BASE=https://dev-developers.aivana.ai` everything works. | Partial: works, but the error misleads | sdk-python#15 F2 |
| 5. Install (pip / pipx / uvx) | Docs > Quickstart, SDKs, Command Line | Clean installs pass on Python 3.10, 3.12, 3.13, 3.14; 3.9 is correctly refused; `pipx install aivana` and `uvx aivana` both work and answer live. | Pass | sdk-python#15 (docs parity) |
| 5. Reproduce in Python SDK | Docs Python tabs + README | All 42 Python examples (16 Docs, 26 README) run against the installed SDK. Sync, async, streaming, Chat, trace and JSON Schema verified live. | Pass | sdk-python#15 F9 |
| 5. Reproduce in CLI | Docs > Command Line | Every statement on /docs/cli holds: options, `--json`, `--trace`, piping, `< /dev/null`, `> answer.md`, exit codes 0-6. 34 offline cases and 7 of 8 live cases pass (the 8th is the test-key message). | Pass | |
| 4. Trace is customer-safe | Docs > Intelligence Trace | No model or provider names in any trace, stream event or CLI output (SDK and CLI, live). `stage`/`route` stream events are undocumented. | Pass, with a doc gap | sdk-python#15 F14 |
| 4. Trace reflects `effort` | "effort is a ceiling ... a lower effort bounds that judgement" | `effort="low"` gave Premium, 3 perspectives, same as `high`, on both decision questions tried (a simple lookup was Efficient at both). | **Fail** | sdk-python#15 F16 |
| 6. Troubleshoot auth | Errors carry code, message, request id | Yes, on SDK and CLI (exit 3). Production 401s now include `request_id`. | Pass | |
| 6. Troubleshoot rate limit / credit / temporary | CLI exit 4 / 5 / 6; SDK error classes | CLI correct for every code. SDK: 504/500/503 are not `UpstreamError`, `RateLimitError` has no retry-after, and network errors and timeouts are not `AivanaError`. | Partial | sdk-python#15 F3-F7 |
| 6. Streaming failure | "Every failure raises" | A mid-stream `error` event ends the SDK loop silently with a partial answer. The CLI handles it (exit 6). | **Fail** (SDK) | sdk-python#15 F1 |
| Cost signals | `max_tokens` is a ceiling; usage reported | `max_tokens` exceeded intermittently. JSON Schema answers report `output_tokens: 0`. | **Fail** | sdk-python#15 F11, F13 |

Takeaway for the journey: the **CLI path is the most reliable route for the demo**. It matches its docs completely, and its exit codes cover the failure cases the SDK still gets wrong. The Python SDK path works for the happy path; the error-handling gaps matter only in the troubleshooting step.
