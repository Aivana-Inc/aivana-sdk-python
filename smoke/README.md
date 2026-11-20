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
| 6 | One async request cancelled while in flight | may be billed, call 3 of 3 (never blocks a release because of a fast answer: see below) |

This SDK has no read-only call (the Node SDK has `quotas()`), so check 3 uses a request the API refuses at validation,
after it has checked the key: an `AuthError` there would mean the key was refused, an `InvalidRequestError` means it was
accepted. It checks the **shape** of answers (not empty, token counts above zero, ids present), never their wording,
because a live model's words change.

## The cancel check never blocks a release because production was fast

Cancelling only means something if the request is still running when the cancel is sent. The script establishes that instead of
assuming it: the request is cancelled after 250 ms, and the outcome is judged on what actually happened.

| What happened | Result | Blocks the release? |
|---|---|---|
| In flight when cancelled, and it stopped promptly with the SDK's cancel error | pass | no |
| The request had **already finished** (an unusually fast answer, or an API error) before the cancel | **not tested** | **no**: shown in the log, the step summary and as a GitHub warning annotation |
| In flight when cancelled, but it ended with some other error, or took 5 s or more to stop | **fail** | **yes**: the SDK's cancel really is broken |

A run where the cancel was not tested is still a pass; if it keeps happening, the warning annotations make it visible. The
deterministic version of the same check runs in CI on every pull request against a stand-in API that always answers slowly
(`test/smoke.test.mjs`, `tests/test_smoke.py`), so cancelling is covered even when production's timing does not allow it.

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
- The calls are a few dozen tokens each. What bounds spending is the test account's balance and, if it holds purchased credit, the key's monthly spend limit (see "Keeping it funded"), not this script.

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

## Setup (a person with GitHub admin and AI Studio access)

The workflow cannot work, and the release gate will block every release, until this is done. The test account is **permanent**:
it is part of how releases are controlled, so it is kept, funded and rotated, not removed after an event.

1. **A dedicated test account** in AI Studio, on an address used for nothing else, named so nobody mistakes it for a customer
   (it appears in the funnel and in Customers). Nobody should use it for anything else.
2. **A key for it** (AI Studio → API Keys) with the **default scopes** (`generate` and `metrics`: the quotas check needs `metrics`).
3. **A GitHub Environment named `production-smoke`** (Settings → Environments → New environment):
   - **Required reviewers:** add yourself. Every run, including the one inside a release, then waits for your click.
   - **Deployment branches and tags:** *Selected branches and tags*: `main` and the tag pattern `v*`. Without this,
     anyone who can push a branch can run the job and read the key.
   - **Environment secrets:** `AIVANA_API_KEY` = the key. Not a repository secret.
4. **Fund the account** (next section), and run **Production smoke test** once by hand to see it pass.

## Keeping it funded

A smoke run is three tiny calls, a fraction of a cent. What actually ends a test account is that **promotional tokens expire**
(60 days by default), so an account funded only that way runs dry on its own, and then every release stops. Fund it on purpose:

| Way | What it takes | Watch out for |
|---|---|---|
| **A small purchase** (the $10 minimum), recommended | One purchase in AI Studio → Billing. Purchased credit lasts a year and a run costs well under a cent, so $10 is years of runs. | Real money can now be spent, so give the key a **monthly spend limit** (AI Studio → API Keys: it limits purchased credit) of a dollar or so. Put the account's credit expiry in a calendar. |
| **Staff-issued promotional tokens** | Aivana Command → Customers → the test account → Promo tokens (a reason is required and kept in the audit log). | They expire, so this is a recurring chore, and a forgotten one stops releases. |

If the account is empty, the smoke test says so in plain words (*THE TEST ACCOUNT IS OUT OF CREDIT: fund it ... this is not an SDK fault*)
and still stops the release, because nothing can be verified without credit. That is a funding fix, not a code fix.

## Rotating the key

When the key may have been exposed, someone who had access leaves, or on whatever schedule you set:

1. AI Studio → API Keys: create a new key on the test account (default scopes).
2. Repository → Settings → Environments → `production-smoke`: replace the `AIVANA_API_KEY` secret (in **both** SDK repositories).
3. Run **Production smoke test** by hand and check it passes (its first step reports a missing or malformed key without calling anything).
4. Revoke the old key in AI Studio.

## If a check fails the first time

The first run against production is also a calibration. If check 4 says *the answer was empty (finish_reason length)*,
the token cap in `TINY` is too small for the model's hidden reasoning: raise `max_tokens` in `smoke.py` and rerun.
Anything else is a finding: quote the request id the script prints.
