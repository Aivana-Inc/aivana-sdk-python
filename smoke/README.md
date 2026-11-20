# Production smoke test

`smoke.py` answers one question before a release goes out: **does the SDK, installed the way a developer installs it,
work against the real Aivana API?** It is a few minutes of the things a new developer does first. It is the Python twin
of the one in [aivana-sdk-node](https://github.com/Aivana-Inc/aivana-sdk-node/tree/main/smoke), which also holds the
checklist for the on-site rehearsal before an event ([EVENT-REHEARSAL.md](https://github.com/Aivana-Inc/aivana-sdk-node/blob/main/smoke/EVENT-REHEARSAL.md)).

| # | Check | Cost |
|---|---|---|
| 1 | The installed SDK is the version being released | free |
| 2 | A made-up key is refused with `AuthError` | free |
| 3 | The real key is accepted, and a bad request is a typed `InvalidRequestError` with a request id | free (refused before any work) |
| 4 | One tiny generation | billed, call 1 of 3 |
| 5 | One tiny streamed generation | billed, call 2 of 3 |
| 6 | One async request cancelled while in flight | may be billed, call 3 of 3 |

This SDK has no read-only call (the Node SDK has `quotas()`), so check 3 uses a request the API refuses at validation,
after it has checked the key: an `AuthError` there would mean the key was refused, an `InvalidRequestError` means it was
accepted. It checks the **shape** of answers (not empty, token counts above zero, ids present), never their wording,
because a live model's words change.

## What it deliberately does not do

- **Provoke a rate limit.** The API's counters are per server task, so the point where blocking starts is not
  predictable, and deliberate bursts put blocked requests in the production logs. The retry logic is proved offline
  (`tests/test_retry.py`).
- **Test timeouts.** A client that gives up does not stop the server's work, so a timed-out call can still be billed.
  Cancelling is tested once (check 6).
- **Say anything about a particular network.** A GitHub runner sits in a data centre, not on a campus.

## Safety

- At most **three billed calls** per run (`MAX_PAID_CALLS`), counted in one place. A fourth is refused by the script.
- The key is sent only to an `https` address (or to this machine, for the offline tests), and every line the script
  prints passes through `redact()`, so the key never reaches a log.
- SDK retries are **off** in the smoke test, so a 429 is reported on the first try instead of hidden behind a retry.
- The calls are a few dozen tokens each. The hard stop on spending is the test account's own balance, not this script.

## Running it

```bash
# nothing is called: checks the key is set and the address is acceptable
AIVANA_API_KEY=ai_live_xxx python smoke/smoke.py --dry-run

# the real thing (three tiny billed calls); EXPECTED_SDK_VERSION is optional
AIVANA_API_KEY=ai_live_xxx EXPECTED_SDK_VERSION=0.4.0 python smoke/smoke.py
```

Exit code `0` means every check passed, `1` a check failed, `2` the setup is wrong and nothing was called.

In GitHub it is the **Production smoke test** workflow (`.github/workflows/smoke.yml`): started by hand
(Actions → Production smoke test → Run workflow) and run automatically as the gate in `publish.yml`, so nothing is
published to PyPI unless it passed. It tests the **built wheel**, installed into a fresh virtual environment, not the
source tree.

Its own tests run offline against a local stand-in for the API (`tests/test_smoke.py`, `tests/test_smoke_workflow.py`);
most make the stand-in misbehave and check the script says FAIL.

## One-time setup (a person with GitHub admin and AI Studio access)

The workflow cannot work, and the release gate will block every release, until this is done. The test account and its
key can be the same ones the Node SDK uses.

1. **A dedicated test account** in AI Studio, on an address used for nothing else, named so nobody mistakes it for a
   customer. Keep it to **promotional tokens only**: an account that has never bought credit can spend nothing but
   those tokens, which is the real spending cap.
2. **A key for it** (AI Studio → API Keys) with the default scopes.
3. **A GitHub Environment named `production-smoke`** (Settings → Environments → New environment):
   - **Required reviewers:** add yourself. Every run, including the one inside a release, then waits for your click.
   - **Deployment branches and tags:** *Selected branches and tags*: `main` and the tag pattern `v*`. Without this,
     anyone who can push a branch can run the job and read the key.
   - **Environment secrets:** `AIVANA_API_KEY` = the key. Not a repository secret.
4. **After the event**, revoke the key and delete the secret, or rotate it.

## If a check fails the first time

The first run against production is also a calibration. If check 4 says *the answer was empty (finish_reason length)*,
the token cap in `TINY` is too small for the model's hidden reasoning: raise `max_tokens` in `smoke.py` and rerun.
Anything else is a finding: quote the request id the script prints.
