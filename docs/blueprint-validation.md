# Blueprint SDK validation — November 11, 2026

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

## Live endpoint result and remaining gate

API documentation names `https://dev-developers.aivana.ai` as the development endpoint.
On November 11, the Node counterpart probed both routes with the existing approved
development configuration and a new nonexistent Blueprint ID. Both returned HTTP 404,
code **blueprint_invocation_unsupported**. No fallback was sent and no keys were logged.

There is no successful live candidate Blueprint run in this evidence. Person 1/API owner
must deploy the routes and supply an authorized saved synthetic Blueprint/version, then
the examples must pass against that candidate and API authorization/isolation/billing
gates must be recorded. The Trello card remains incomplete until that acceptance run.
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

Still not proved: a run against a DEPLOYED environment (the dev API at the time of writing may
not yet carry the routes), a real model's answer, and the rolling-deploy 404 on a real deploy.
Those remain release gates, with SDK-maintainer review.
