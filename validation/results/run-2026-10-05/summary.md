# Live run 1 - Oct 5, 2026 (macOS, Python 3.14.0, aivana 0.3.0, dev-developers.aivana.ai)
pytest: 3 failed, 53 passed, 10 xfailed, 1 xpassed in 73 s
Matrix totals: PASS 46, DEFECT (known) 10, FAIL 3, FIXED? 1
- PY-LIV-11 FAIL: max_tokens=40 -> output_tokens 67, finish_reason stop  (-> F11)
- PY-LIV-33, PY-LIV-40 FAIL: 429 "per-minute request limit reached" (suite pacing issue, not SDK)
- PY-LIV-02 XPASS: dev host 401 includes request_id (F4 narrowed to production host)
- PY-LIV-03 XFAIL: default host developers.aivana.ai rejects the test key (F2 confirmed)
All other live cases passed. Evidence: evidence.jsonl in this folder (keys redacted).
