# Blueprint SDK validation

Sections are dated and kept as the record of what was true then; the newest result is at the bottom.
The first sections describe November 11, when no API had the routes, and are superseded by the later ones.

## November 11, 2026

Scope: [Iteration 6 SDK card](https://trello.com/c/0Rb6idgP), SDK portion of API #367.
Windows, Python 3.12.14. Both SDK repositories were freshly cloned and then pulled
from main before implementation; both pulls reported up to date.

## Delivered and checked

- Sync and async normal/streaming invocation using dedicated Blueprint routes.
- Explicit version/latest, runtime-only bodies and typed resolved Blueprint references.
- Unsupported-route versus missing-resource errors; no settings overrides, retries or fallback.
- Stream errors/truncation and explicit iterator close release the transport.
- Candidate examples and a byte-identical synthetic fixture shared with the Node SDK.
- Full Python suite: **227 passed, 1 skipped**. This includes 107 Blueprint contract tests
  and four example executions over actual loopback HTTP, covering pinned/latest and
  normal/streaming. No model providers or external generation were used by these tests.
- Configured Ruff checks pass. Wheel and source distribution build; the installed wheel
  exposes the new module and types, and the source distribution retains the fixture.
- Async checks needed normal Windows event-loop access; the restricted process could not
  initialize its local socketpair. The successful run used the same tests unmodified.

## Live endpoint result and remaining gate (as of November 11; see the later sections)

API documentation names `https://dev-developers.aivana.ai` as the development endpoint.
On November 11, the Node counterpart probed both routes with the existing approved
development configuration and a new nonexistent Blueprint ID. Both returned HTTP 404,
code **blueprint_invocation_unsupported**. No fallback was sent and no keys were logged.

There is no successful live candidate Blueprint run in this evidence. Person 1/API owner
must deploy the routes and supply an authorized saved synthetic Blueprint/version, then
the examples must pass against that candidate and API authorization/isolation/billing
gates must be recorded.
SDK-maintainer review and verified production API rollout are release gates; this work
publishes no package or production deployment.

See [integration and repeat instructions](blueprint-invocation.md).

## Run against the merged API, November 24, 2026

The API half (aivana-intelligence-api#400, merged) now exists, so the SDK was driven against it
for the first time. Not a deployed environment: the real API application ran on loopback under
uvicorn with its real middleware, routes, admission, billing and Blueprint store, a governed
organization and a real API key; only the model engine's answer was faked, as in the API's own
`script/test_blueprint_invocation.py`. The real SDK made the calls over actual HTTP.

Checked and passing (sync and async where the SDK has both):

- A pinned version returns the resolved `blueprint` reference, and the saved settings reach
  the engine (the SDK sends only runtime input).
- `latest` resolves once and names the version that ran; a pinned version stays pinned after
  a newer one is saved.
- Streaming: the `done` frame carries the resolved Blueprint; `contextlib.aclosing` on the
  async stream.
- A missing Blueprint (unknown id, missing version) is `blueprint_not_found`, never reported as
  "unsupported by this API".
- A settings override, version `0` and `"Latest"` are refused and nothing reaches the engine.
- An API without the routes (the router's own 404, as an older task in a rolling deploy
  answers) raises `UnsupportedAPIError` (`blueprint_invocation_unsupported`) and the SDK sends
  nothing else: no fallback to ordinary Generate.
- No key is a 401.

Still not proved at that time: a run against a DEPLOYED environment (the next section), a real model's
answer, and the rolling-deploy 404 on a real deploy.

## Run against the development API, November 24, 2026

Environment: the development API at `https://dev-developers.aivana.ai`, after the API change that adds
the routes (aivana-intelligence-api#400) was deployed there by its normal pipeline that day. The deployed
revision identifier was not recorded. A scoped, spend-limited development key from a synthetic workspace
was used and never printed. Only requests for a deliberately nonexistent Blueprint id were sent, so
nothing was generated or charged. The SDK was run from the head of the pull request that added it.

Passing, from this SDK against the deployed API:

- Pinned version 1, `latest`, the streaming route and the async call each answered `blueprint_not_found`:
  the routes are deployed and Blueprint storage is configured. None was reported as `UnsupportedAPIError`.
  Request ids: `req_48bb329e776f1418eaf89e5a`, `req_7a2bee6b705379ba783708af`, `req_f64a87ba4ad87edaa5278b56`.
- Version `0`, `"Latest"` and a saved-settings override are refused client-side with nothing sent.

Direct probes of the same routes returned `422` for a malformed version, with the API's own wording.

**Not verified as of this record:** a successful pinned or `latest` run, normal, streaming or async,
against a saved Blueprint on a deployed environment; workspace isolation, member permissions and billing
on a deployed environment; the routes on production; a real model's answer; the rolling-deploy 404 on a
real deploy. Update this section with the date and request ids when any of these is run.
