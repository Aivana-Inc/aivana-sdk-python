<!-- TARGET: comment on Aivana-Inc/aivana-sdk-python#15
     Replace #NN placeholders with the numbers of the issues once filed. Attach or link results/matrix.md and results/install.md. -->
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
- [x] Async and streaming behavior are validated (live). A failed stream is the exception: #NN.
- [x] CLI basic / JSON / Trace paths are validated (offline + live).
- [x] Representative errors and exit codes are validated (CLI exit codes 0-6 all correct; SDK gaps filed).
- [x] Published docs and examples are checked against actual behavior (42 examples, /docs/cli statement by statement).
- [x] Every failed case has reproducible evidence (test ID, request id, repro snippet).
- [x] Substantive defects are filed as focused issues (below).
- [x] Findings are incorporated into the AI Studio integrated developer journey: aivana-ai-studio#149 (comment).

### Issues filed
| Issue | Findings | Severity | Owner |
|---|---|---|---|
| #NN A failed stream ends silently with a partial answer | F1 | High | SDK |
| #NN Not every failure raises AivanaError | F5, F15 | Medium | SDK + CLI |
| #NN Retrying a failed Chat.send() sends the question twice | F8 | Medium | SDK |
| #NN Error classes vs retry/support docs (504, Retry-After, 422, X-Request-Id) | F3, F4, F6, F7 | Low | SDK |
| #NN max_tokens is not enforced as a ceiling | F11 | Medium | API |
| #NN JSON Schema answers report output_tokens = 0 | F13 | Medium | API |
| #NN effort="low" does not bound intelligence | F16 (new) | Medium | API / Docs |
| #NN Test key on production: misleading error message | F2 | Low | API + CLI |
| #NN Docs parity: configure snippet, top_p, stream events, extract shape, 3.14 classifier | F9, F10, F12, F14 | Low | Docs |

### Changed since the Oct 5 report (0.3.0)
- 0.3.1 moved the default host to `api.aivana.ai`; the suite follows it.
- **F4 server half fixed:** production 401s now include `request_id`.
- **F2 reframed, High -> Low:** test keys are documented (Docs > API Keys) as accepted only in their own environment, so the 401 on production is by design. What remains is the misleading error text.
- **F12 / F14 narrowed** to documentation questions after checking the Docs wording.
- **New:** F15 (an unparseable 200 crashes the CLI with a traceback), F16 (effort is not a ceiling).
- **Not a defect:** the SDK always sends `"mode": "aivana_mmi"`, a fixed constant the conformance spec expects.

The CLI matches its documentation completely and handles every failure case. It is the most reliable path for the journey demo.
