# Aivana Python SDK - validation matrix

aivana 0.3.1 | Python 3.14.0 | Darwin | live base https://dev-developers.aivana.ai | key set: yes | 2026-10-20T17:39:48

Totals: DEFECT (known) 16, FIXED? (re-check) 1, PASS 102

| ID | Area | Check | Mode | Result | Finding | Detail |
|---|---|---|---|---|---|---|
| PY-CFG-01 | Configure | `aivana.api_key = ...` (Docs > SDKs example) sends X-API-Key | offline | PASS |  |  |
| PY-CFG-02 | Configure | `set_api_key()` is equivalent to assignment | offline | PASS |  |  |
| PY-CFG-03 | Configure | Falls back to AIVANA_API_KEY, read per request (export after import) | offline | PASS |  |  |
| PY-CFG-04 | Configure | A key set in code wins over AIVANA_API_KEY | offline | PASS |  |  |
| PY-CFG-05 | Configure | No key anywhere: no header sent, 401 surfaces as AuthError | offline | PASS |  |  |
| PY-CFG-06 | Configure | Default api_base is the documented hosted API; trailing slash normalised | offline | PASS |  |  |
| PY-CFG-07 | Configure | Docs > SDKs configure snippet works when the env var is unset | offline | DEFECT (known) | F9 |  |
| PY-CHT-01 | Conversations | Chat sends full history plus previous_intent / pending_action | offline | PASS |  |  |
| PY-CHT-02 | Conversations | Chat options apply every turn; send() overrides win for that turn | offline | PASS |  |  |
| PY-CHT-03 | Conversations | reset() starts a fresh conversation | offline | PASS |  |  |
| PY-CHT-04 | Conversations | A failed send() does not corrupt history (retry is safe) | offline | DEFECT (known) | F8 |  |
| PY-CLI-01 | CLI | `aivana --version` runs from the installed console script and names the SDK version | offline | PASS |  |  |
| PY-CLI-02 | CLI | `python -m aivana` is the same program (README) | offline | PASS |  |  |
| PY-CLI-03 | CLI | `aivana --help` lists every option Docs > Command Line documents, and both env vars | offline | PASS |  |  |
| PY-CLI-04 | CLI | --help's exit-code table matches the Docs/README table (0-6, 130) | offline | PASS |  |  |
| PY-CLI-05 | CLI | No model/provider option exists (Docs: 'No model picker, on purpose') | offline | PASS |  |  |
| PY-CLI-06 | CLI | The bare command on a terminal prints help (exit 2); `aivana help` exits 0 | offline | PASS |  |  |
| PY-CLI-10 | CLI | Basic question: answer on stdout only, exit 0, POST /v1/generate:stream with X-API-Key | offline | PASS |  |  |
| PY-CLI-11 | CLI | `aivana "..." > answer.md` saves just the answer, even with the progress line on a terminal | offline | PASS |  |  |
| PY-CLI-12 | CLI | Every documented option reaches the wire under its SDK name (README option table) | offline | PASS |  |  |
| PY-CLI-13 | CLI | Options left off are not sent (left to Aivana); --no-web sends web_search=false | offline | PASS |  |  |
| PY-CLI-14 | CLI | Reserved word is refused with a hint; `aivana ask ...` is the way around it (README) | offline | PASS |  |  |
| PY-CLI-15 | CLI | Abbreviated options are refused (`--temp` is not --temperature) | offline | PASS |  |  |
| PY-CLI-20 | CLI | Piped text is sent ahead of the question (`git diff \| aivana "Review this change"`) | offline | PASS |  |  |
| PY-CLI-21 | CLI | Piped text alone is the question; `aivana "..." < contract.txt` works | offline | PASS |  |  |
| PY-CLI-22 | CLI | Docs: with nothing piped, `< /dev/null` answers at once (no 3 s wait, no note) | offline | PASS |  |  |
| PY-CLI-23 | CLI | Docs: an open-but-silent stdin waits about 3 s, says so on stderr, then sends just the question | offline | PASS |  |  |
| PY-CLI-24 | CLI | Binary piped input is refused locally with a pointer to --image (exit 2) | offline | PASS |  |  |
| PY-CLI-30 | CLI | --json waits for the whole response (POST /v1/generate) and prints parseable JSON | offline | PASS |  |  |
| PY-CLI-31 | CLI | --trace prints the Intelligence Trace on stderr after the answer; stdout stays the answer | offline | PASS |  |  |
| PY-CLI-32 | CLI | --image: non-image files are refused locally (exit 2) with how to send a document instead | offline | PASS |  |  |
| PY-CLI-33 | CLI | --image with a missing file names the file (exit 2, nothing sent) | offline | PASS |  |  |
| PY-CLI-34 | CLI | A 200 --json response the SDK cannot parse ends in a clean `aivana: error:` (exit 1), not a traceback | offline | DEFECT (known) | F17 |  |
| PY-CLI-40 | CLI | No AIVANA_API_KEY: exit 3 before any request, with how to set it | offline | PASS |  |  |
| PY-CLI-41 | CLI | Each documented HTTP error maps to the documented exit code, message + request id on stderr | offline | PASS |  |  |
| PY-CLI-42 | CLI | A 422 validation error names the flag to fix (exit 1) | offline | PASS |  |  |
| PY-CLI-43 | CLI | Bad usage exits 2 with no request (unknown --effort, non-number --max-tokens, no question) | offline | PASS |  |  |
| PY-CLI-44 | CLI | Unreachable API: exit 6 ('safe to retry') | offline | PASS |  |  |
| PY-CLI-45 | CLI | An error frame inside a 200 stream exits 6, and partial text is flagged as incomplete | offline | PASS |  |  |
| PY-CLI-46 | CLI | A cut-off answer (finish_reason=length) says so on stderr | offline | PASS |  |  |
| PY-CLI-47 | CLI | The API key never appears in stdout or stderr, on success or failure | offline | PASS |  |  |
| PY-CLI-50 | CLI | AIVANA_API_BASE that is not a URL is refused locally (exit 2) | offline | PASS |  |  |
| PY-CLI-51 | CLI | Plain http:// to a non-local host warns the key travels unencrypted | offline | PASS |  |  |
| PY-CLI-52 | CLI | Plain http:// to localhost is ordinary local development (no warning) | offline | PASS |  |  |
| PY-CLI-53 | CLI | With AIVANA_API_BASE unset the CLI calls the documented default (https://api.aivana.ai) | offline | PASS |  |  |
| PY-CLI-L01 | CLI | Live: basic question streams an answer to stdout, nothing on stderr, exit 0 | live | PASS |  |  |
| PY-CLI-L02 | CLI | Live: --json prints a GenerateResponse with answer, usage and request_id | live | PASS |  |  |
| PY-CLI-L03 | CLI | Live: --trace shows the Intelligence Trace on stderr only, with no model/provider names | live | PASS |  |  |
| PY-CLI-L04 | CLI | Live: piped text is answered (`echo ... \| aivana "..."`) | live | PASS |  |  |
| PY-CLI-L05 | CLI | Live: an invalid key exits 3 with a request id, and the key is not echoed | live | PASS |  |  |
| PY-CLI-L06 | CLI | Live: `--shape extract --json` (Docs/README example) returns a structured result | live | PASS |  |  |
| PY-CLI-L07 | CLI | Live: --image attaches a PNG and the request is accepted | live | PASS |  |  |
| PY-CLI-L08 | CLI | Live: out of the box (AIVANA_API_BASE unset, Docs/Quickstart) a test key works | live | DEFECT (known) | F2 |  |
| PY-DOC-API-KEYS | Docs parity | Every Python example on docs/api-keys runs against the installed SDK | offline | PASS |  |  |
| PY-DOC-CONVERSATIONS | Docs parity | Every Python example on docs/conversations runs against the installed SDK | offline | PASS |  |  |
| PY-DOC-ERRORS-RETRIES | Docs parity | Every Python example on docs/errors-retries runs against the installed SDK | offline | PASS |  |  |
| PY-DOC-FILES-DOCUMENTS | Docs parity | Every Python example on docs/files-documents runs against the installed SDK | offline | PASS |  |  |
| PY-DOC-GENERATE | Docs parity | Every Python example on docs/generate runs against the installed SDK | offline | PASS |  |  |
| PY-DOC-INTELLIGENCE-TRACE | Docs parity | Every Python example on docs/intelligence-trace runs against the installed SDK | offline | PASS |  |  |
| PY-DOC-PARAMETERS | Docs parity | Every Python example on docs/parameters runs against the installed SDK | offline | PASS |  |  |
| PY-DOC-QUICKSTART | Docs parity | Every Python example on docs/quickstart runs against the installed SDK | offline | PASS |  |  |
| PY-DOC-README | Docs parity | Every Python example on README runs against the installed SDK | offline | PASS |  |  |
| PY-DOC-SDKS | Docs parity | Every Python example on docs/sdks runs against the installed SDK | offline | PASS |  |  |
| PY-DOC-STREAMING | Docs parity | Every Python example on docs/streaming runs against the installed SDK | offline | PASS |  |  |
| PY-DOC-STRUCTURED-OUTPUTS | Docs parity | Every Python example on docs/structured-outputs runs against the installed SDK | offline | PASS |  |  |
| PY-ERR-01 | Errors | Each documented status maps to the documented AivanaError subclass + code | offline | PASS |  |  |
| PY-ERR-02 | Errors | 422 details (which field is wrong) are kept on the exception | offline | PASS |  |  |
| PY-ERR-03 | Errors | Any 422 is an InvalidRequestError (docs: '400 or 422') | offline | DEFECT (known) | F3 |  |
| PY-ERR-04 | Errors | request_id is available on errors (falls back to X-Request-Id header) | offline | DEFECT (known) | F4 |  |
| PY-ERR-05 | Errors | Network failure raises an AivanaError subclass ('every failure raises') | offline | DEFECT (known) | F5 |  |
| PY-ERR-06 | Errors | Timeout raises an AivanaError subclass | offline | DEFECT (known) | F5 |  |
| PY-ERR-07 | Errors | RateLimitError exposes the Retry-After wait the docs say to honour | offline | DEFECT (known) | F6 |  |
| PY-ERR-08 | Errors | 504 (documented retryable) raises a catchable, retryable error class | offline | DEFECT (known) | F7 |  |
| PY-GEN-01 | Generate | Parses a real dev-API response: answer, usage, finish_reason, notices | offline | PASS |  |  |
| PY-GEN-02 | Generate | POSTs /v1/generate with prompt; unset options are omitted | offline | PASS |  |  |
| PY-GEN-03 | Generate | Every documented option reaches the wire in snake_case | offline | PASS |  |  |
| PY-GEN-04 | Generate | System prompt > 8000 chars raises InvalidRequestError before any request | offline | PASS |  |  |
| PY-GEN-05 | Generate | Attachments: mimeType normalised to mime_type; bad item rejected | offline | PASS |  |  |
| PY-GEN-06 | Generate | response_format sent exactly as given; non-dict rejected client-side | offline | PASS |  |  |
| PY-GEN-07 | Generate | Tolerates new fields the server adds (forward compatible) | offline | PASS |  |  |
| PY-GEN-08 | Generate | Non-JSON 200 (proxy page) raises AivanaError, not JSONDecodeError | offline | PASS |  |  |
| PY-GEN-09 | Generate | Redirects are not followed, so the key never leaves api_base | offline | PASS |  |  |
| PY-GEN-10 | Generate | generate_async returns the same GenerateResponse | offline | PASS |  |  |
| PY-GEN-11 | Generate | messages= is sent instead of prompt (manual history) | offline | PASS |  |  |
| PY-INS-01 | Install | Package installs from PyPI and reports its version | offline | PASS |  |  |
| PY-INS-02 | Install | Runs on the documented minimum (Python >= 3.10) | offline | PASS |  |  |
| PY-INS-03 | Install | Every name the docs use is importable from `aivana` | offline | PASS |  |  |
| PY-LIV-01 | Auth | Invalid key -> AuthError with code, message and request_id | live | PASS |  |  |
| PY-LIV-02 | Auth | Errors carry the request_id the docs say to quote to support (dev host) | live | PASS |  |  |
| PY-LIV-03 | Auth | Out of the box (default api_base, no URL configured) the test key works | live | DEFECT (known) | F2 |  |
| PY-LIV-04 | Auth | Errors from the default (production) host also carry request_id | live | FIXED? (re-check) | F4 |  |
| PY-LIV-10 | Generate | Basic generate (Docs > SDKs example) returns answer, usage, finish_reason, notices | live | PASS |  |  |
| PY-LIV-11 | Generate | max_tokens is a ceiling: output_tokens <= max_tokens | live | DEFECT (known) | F11 |  |
| PY-LIV-12 | Generate | intelligence_trace=True returns trace with steps and summary | live | PASS |  |  |
| PY-LIV-13 | Generate | Trace stays customer-safe: no provider/model names leak | live | PASS |  |  |
| PY-LIV-14 | Generate | assistant_name is honoured | live | PASS |  |  |
| PY-LIV-15 | Generate | messages= with a system message works (manual history) | live | PASS |  |  |
| PY-LIV-16 | Generate | web_search off + a question asking for the web -> web_search_off notice | live | PASS |  |  |
| PY-LIV-17 | Generate | stop_sequences: the marker is not returned | live | PASS |  |  |
| PY-LIV-18 | Generate | output_shape='extract' returns structured or structured_error | live | PASS |  |  |
| PY-LIV-19 | Structured | response_format json_schema -> validated .structured, or documented response_format_not_available | live | PASS |  |  |
| PY-LIV-20 | Structured | Unsupported schema -> InvalidRequestError invalid_response_schema, not billed | live | PASS |  |  |
| PY-LIV-21 | Errors | Out-of-range parameter (temperature=5) -> InvalidRequestError with details | live | PASS |  |  |
| PY-LIV-22 | Structured | A successful json_schema answer reports its output tokens in usage | live | DEFECT (known) | F13 |  |
| PY-LIV-23 | Generate | effort is a ceiling: effort='low' keeps a decision question below the top level (Premium) | live | DEFECT (known) | F16 |  |
| PY-LIV-30 | Streaming | stream=True: deltas arrive incrementally and done carries usage/notices | live | PASS |  |  |
| PY-LIV-31 | Streaming | stream + intelligence_trace emits trace events | live | PASS |  |  |
| PY-LIV-32 | Streaming | Invalid key on the stream raises AuthError | live | PASS |  |  |
| PY-LIV-33 | Async | generate_async and generate_stream work end to end | live | PASS |  |  |
| PY-LIV-34 | Streaming | Without intelligence_trace, a stream sends only documented events | live | DEFECT (known) | F14 |  |
| PY-LIV-35 | Streaming | Stream route/stage/trace payloads stay customer-safe (no model/provider names) | live | PASS |  |  |
| PY-LIV-40 | Conversations | Chat remembers earlier turns (Docs > SDKs > Conversations) | live | PASS |  |  |
| PY-STR-01 | Streaming | stream=True yields delta chunks that join into the answer; done carries usage | offline | PASS |  |  |
| PY-STR-02 | Streaming | Streams hit POST /v1/generate:stream with the same body | offline | PASS |  |  |
| PY-STR-03 | Streaming | json_schema + stream refused client-side with the documented code | offline | PASS |  |  |
| PY-STR-04 | Streaming | HTTP 401 on the stream raises AuthError (not an httpx error) | offline | PASS |  |  |
| PY-STR-05 | Streaming | Async generate_stream yields the same chunks | offline | PASS |  |  |
| PY-STR-06 | Streaming | Unknown/trace events pass through without breaking iteration | offline | PASS |  |  |
| PY-STR-07 | Streaming | Mid-stream `error` event raises AivanaError ('every failure raises') | offline | DEFECT (known) | F1 |  |
