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

The SDK version is pinned in `requirements.txt` (`aivana==0.3.1`), which is what a plain run tests.

## Testing another version, or a release candidate

The pin is only the default. To test a different release, or a wheel that is not published yet, name it (the pin is not edited):

```bash
python -m build --wheel                    # in the repo root
AIVANA_SDK_SPEC=/path/aivana-0.4.0-py3-none-any.whl \
AIVANA_EXPECT_SDK_VERSION=0.4.0 \
AIVANA_RESULTS_DIR=/tmp/validation-results \
  bash run_validation.sh
# or a published version:  AIVANA_SDK_SPEC=aivana==0.4.0
```

`AIVANA_EXPECT_SDK_VERSION` makes the run stop (exit 2) unless exactly that version is installed, so a gate cannot pass by testing the
wrong package. `AIVANA_RESULTS_DIR` keeps the run from overwriting the committed evidence in `results/`. A later version can turn a known
defect into `FIXED? (re-check)`: that is reported with a `NOTICE` line and does not fail the run (pytest's own summary still says
"1 failed" for it, because `xfail_strict` is on; the exit status is what counts). Set `AIVANA_STRICT_KNOWN=1` if you want a fixed
defect to fail the run until the known-defect list is updated.

## Exit code

`run_validation.sh` exits with the suite's verdict, so a script or a release gate can trust it (it used to end in `|| true`, which made every run exit 0):

| Exit | Meaning |
|---|---|
| 0 | nothing unexpected: every case is PASS, DEFECT (known), FIXED? (re-check) or SKIP |
| 1 | at least one case **FAILED**, or a test or its setup errored (including one that is not in the matrix) |
| 2 | the installed version is not the one in `AIVANA_EXPECT_SDK_VERSION` |
| 5 | pytest collected no tests (a filter that matches nothing): not a pass |

Without a key the live cases skip and the run still exits 0. `tests/test_exit_status.py` pins all of this.
