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
