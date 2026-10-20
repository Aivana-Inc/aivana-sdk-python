# Live run 2 - Oct 20, 2026 (macOS, Python 3.14.0, aivana 0.3.1, dev-developers.aivana.ai)
pytest: 57 passed, 12 xfailed, 2 xpassed in 228 s
Matrix totals: PASS 50, DEFECT (known) 12, FIXED? 2, FAIL 0
Changes since run 1 (0.3.0, Oct 5):
- 0.3.1 default api_base is https://api.aivana.ai (was developers.aivana.ai). PY-CFG-06 updated.
- PY-LIV-03 XFAIL: api.aivana.ai still rejects the ai_test_ key with 401 invalid_api_key (F2 still open on the new host).
- PY-LIV-04 XPASS: api.aivana.ai 401 now includes request_id (req_e99ee04dd04206f9077ae09d). F4 is fixed server-side for
  production; the SDK still ignores the X-Request-Id header (PY-ERR-04 offline stays a known defect).
- PY-LIV-11 XPASS (borderline): max_tokens=40 -> output_tokens 44, finish_reason stop. Inside the test's +5 tolerance but
  still over the ceiling and not reported as "length"; Oct 5 was 67. F11 improved, not clearly fixed.
- No 429s this run (6 s pacing between live tests).
Evidence: evidence.jsonl in this folder (keys redacted).

## Run 2b - same day, CLI added (tests/test_cli.py)
pytest: 116 passed, 14 xfailed, 2 xpassed in 337 s
Matrix totals: PASS 90, DEFECT (known) 14, FIXED? 2, FAIL 0
- CLI offline: 30 cases (installed console script as a subprocess, fake API on 127.0.0.1) - all pass except F15.
- CLI live: 7 of 8 pass (basic, --json, --trace, pipe, invalid key -> exit 3, --shape extract --json, --image).
- PY-CLI-L08 (F2): AIVANA_API_BASE unset + valid ai_test_ key -> exit 3, "Invalid or expired API key. Generate a new key",
  hint `export AIVANA_API_KEY=ai_live_...` - misleading: the key is valid on dev.
- NEW F15: --json with a 200 body missing a required field (intent) crashes with a raw pydantic traceback (exit 1),
  not `aivana: error:`; the SDK raises pydantic.ValidationError, not an AivanaError. Low severity (the real API sends it).
- Not a defect: the SDK always sends "mode": "aivana_mmi" (fixed constant; conformance/cli.json expects it).

## Final run - 2026-10-20 17:40 (all suites: offline, live, CLI, docs examples)
pytest: 158 passed, 16 xfailed, 1 xpassed in 348 s
Matrix totals: PASS 102, DEFECT (known) 16, FIXED? 1 (F4 server side), FAIL 0
Install checks (install_check.sh): 8/8 PASS - pip on 3.10/3.12/3.13/3.14, 3.9 refused, pipx, uvx.
Docs examples: 42/42 Python examples (16 Docs, 26 README on PyPI) run against the installed SDK.
- F2 reframed: test keys are documented as environment-specific (Docs > API Keys); the defect is the
  misleading "Invalid or expired" message + ai_live_ hint. Low.
- F11 reproduced: max_tokens=40 -> 57 output tokens, finish_reason stop (req_17cb14c01671d3bb49a952a0).
- F13 reproduced: json_schema success, output_tokens 0 (req_16542cc66bbba421f77462fc).
- NEW F16: effort=low reaches Premium / 3 perspectives, same as high (effort_probe.json; PY-LIV-23
  req_bea4bee4c61c8d5e856849c1).
- F12/F14 narrowed to documentation questions (see drafts/09-docs-parity.md).
