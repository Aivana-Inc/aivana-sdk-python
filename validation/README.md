# Aivana Python SDK validation

A repeatable test suite for the official `aivana` Python SDK and its `aivana` command-line tool (PyPI), tested as an external developer would use them. It's the Python part of Charter Rev2, Objective 1 / Deliverable 2 (CLI & SDK Validation).

## Run it

```bash
cd validation          # in a clone of aivana-sdk-python
bash run_validation.sh                       # offline checks: free, no key needed

export AIVANA_API_KEY=ai_test_...            # sponsor-approved test key
bash run_validation.sh                       # adds the live checks (dev host)
```

The live checks default to `https://dev-developers.aivana.ai`, the only host that accepted the team's `ai_test_` key in the Sept 29 first-call test. To test another host, set `AIVANA_API_BASE`. Live calls use `effort="low"` and small `max_tokens`, so a full run costs very little credit.

## What you get

| File | Contents |
|---|---|
| `results/matrix.md` / `.csv` | One row per case with PASS / FAIL / DEFECT (known) / SKIP and a finding ID |
| `results/evidence.jsonl` | Redacted request and response evidence from each live call (ids, usage, latency, errors) |

## How to read the results

- **PASS**: the SDK behaves as documented.
- **DEFECT (known)**: the test checks for documented behavior and the SDK doesn't meet it yet. The finding ID (F1, F2, ...) links to the validation report.
- **FIXED? (re-check)**: a known-defect test now passes, so the SDK changed. Re-verify it and update the report.
- **FAIL**: a new, unexpected problem. Investigate it and add a finding.

## Layout

```
conftest.py          fixtures (offline/live), key redaction, matrix writer
tests/test_offline.py  40 cases: config, request building, parsing, streaming, errors, Chat (HTTP mocked with respx)
tests/test_live.py     24 cases: auth, generate options, trace, structured output, streaming, async, Chat, stream events
tests/test_cli.py      the installed `aivana` command run as a real process: help/version, options on the wire,
                       stdin/pipes, --json, --trace, --image, exit codes, API base (offline: a fake API on
                       127.0.0.1; live: 8 cheap calls to the dev host)
```

The CLI cases check against the README "Command line" section and AI Studio > Docs > Command Line
(`/docs/cli`, source `src/data/docsData.ts` in aivana-ai-studio).

To add a case, write a test with `@pytest.mark.case("PY-XXX-NN", "Area", "what it checks")`. If it documents a defect, add `@pytest.mark.xfail(strict=True, reason="Fn: ...")`.

The SDK version is pinned in `requirements.txt` (`aivana==0.3.1`). Bump it when Aivana publishes a new release, then rerun.
