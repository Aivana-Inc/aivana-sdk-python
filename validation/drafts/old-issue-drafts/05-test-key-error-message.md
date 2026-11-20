<!-- TARGET: Aivana-Inc/aivana-intelligence-api (the 401 wording) + Aivana-Inc/aivana-sdk-python (CLI hint).
     Our account cannot see aivana-intelligence-api: file in aivana-sdk-python and ask a maintainer to transfer/split.
     labels: enhancement, OSU Developer Platform Team | finding F2 (Low; was High on Oct 5) -->
# A test key on the production API gets "Invalid or expired API key", not the environment mismatch the Docs describe

Found during external-developer validation (#15, part of #14).

## Background
AI Studio > Docs > API Keys says test keys (`ai_test_`) are issued by a pre-production environment, are accepted only there, and "won't work against api.aivana.ai". So refusing one on `https://api.aivana.ai` (the SDK and CLI default since 0.3.1) is by design. The same page tells developers what a refusal means: *"If a request is refused as unauthorized and your key starts with ai_test_, you are most likely sending a key from another environment: use a live key from AI Studio."*

## What happens
Neither the API nor the CLI says that:

- API (production, 401): `invalid_api_key`, *"Invalid or expired API key. Generate a new key or check its expiry."* (`req_90829f901576ccebdc576ec6`, 2026-10-20)
- CLI, exit 3:
  ```
  aivana: error: Invalid or expired API key. Generate a new key or check its expiry. (request id: req_92366b3a1251757e3e6cecf1)
    Create a new key in AI Studio > API Keys, then run:
      export AIVANA_API_KEY=ai_live_...
  ```

The same key works on `https://dev-developers.aivana.ai` (every other live case in the suite). A developer holding a valid test key is told it is invalid or expired. That is what our team concluded on Sept 29 before we understood the environments.

## Reproduce
```bash
export AIVANA_API_KEY=ai_test_...      # a valid key from a pre-production environment
unset AIVANA_API_BASE                   # the Docs: "no URL to configure"
aivana "Reply with the single word: ok"; echo "exit $?"
```
Suite cases: `PY-LIV-03` (SDK), `PY-CLI-L08` (CLI).

## Suggested fix
- API: when the presented key's prefix names another environment (`ai_test_` on production, or `ai_live_` on a pre-production host), return a distinct code (e.g. `key_wrong_environment`) and a message saying so. The prefix is not secret, so this reveals nothing.
- CLI/SDK (works today, no API change needed): on a 401 with an `ai_test_` key and the default base, add the Docs' own hint: "This is a test key; test keys work only in the environment that issued them. Use a live key from AI Studio, or set AIVANA_API_BASE to that environment."
- Docs > Quickstart / Command Line: next to "no URL to configure", link the API Keys page's "Live and test keys" section.

## Environment
aivana 0.3.1 (PyPI) SDK and CLI, Python 3.14.0, macOS arm64, 2026-10-20.
