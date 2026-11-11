# Saved Blueprint invocation — unreleased candidate

Implements the SDK portion of [API #367](https://github.com/Aivana-Inc/aivana-intelligence-api/issues/367)
and [Iteration 6 SDK integration](https://trello.com/c/0Rb6idgP).
These methods are candidate code, not an available published release. Do not publish or
enable them until the API routes are deployed and verified in production and SDK maintainers approve release.

Create and save the Blueprint in AI Studio. Invocation uses its ID, an explicit version
and runtime input. Management from scoped API keys belongs to API #366.

## Contract

- Normal: `POST /v1/blueprints/{id}/versions/{version}/generate`.
- Stream: the same path with `generate:stream`.
- Version is a positive safe integer, or the literal `latest` explicitly. No default latest.
- Runtime fields: prompt, messages, attachments, metadata, previous_intent, pending_action,
  continue_, assistant_name and intelligence_trace. Unknown options and saved generation
  settings are rejected locally, including settings explicitly passed as None.
- No automatic retries or fallback to ordinary Generate.
- Router 404: `UnsupportedAPIError`, code `blueprint_invocation_unsupported`.
  Resource 404: `AivanaError`, code `blueprint_not_found`.
- Normal responses expose typed `result.blueprint.id` and numeric `result.blueprint.version`.
  Streams expose the same reference in `done.data['blueprint']`. Missing/mismatched references
  and missing done frames are errors. A response error does not imply no credit was used;
  do not automatically repeat generation.
- Existing authentication, validation details and request IDs are preserved. Mid-stream
  errors raise instead of silently presenting a partial answer as complete.
- Module-level API key and API base configuration is read per request, just like Generate.

## Candidate examples

Install this source checkout with `python -m pip install -e .`, then configure
`AIVANA_API_KEY`, `AIVANA_API_BASE`, `AIVANA_BLUEPRINT_ID`, `AIVANA_BLUEPRINT_VERSION`.
Keep credentials out of source and logs. Each run can consume normal generation credit.

```sh
python examples/blueprints/invoke.py
python examples/blueprints/invoke.py --stream
```

```python
result = aivana.blueprints.generate(id='bp_example', version=3, prompt='Draft a reply.')
print(result.blueprint)
for chunk in aivana.blueprints.stream(id='bp_example', version=3, prompt='Draft a reply.'):
    if chunk.event == 'delta':
        print(chunk.delta, end='')
    if chunk.event == 'done':
        print(chunk.data['blueprint'])
```

Async equivalents are `await aivana.blueprints.generate_async(...)` and
`async for chunk in aivana.blueprints.stream_async(...)`. All methods accept `timeout`
in seconds, following the existing httpx timeout behavior. To stop early, use
`contextlib.closing(aivana.blueprints.stream(...))` or `contextlib.aclosing` for the async
iterator, so the connection closes immediately when a loop breaks. No history is stored.

## Repeatable checks and release gate

```sh
python -m pip install . pytest build ruff==0.6.9
python -m pytest tests -q
python -m ruff check --select E9,F63,F7,F82 .
python -m build
```

`conformance/blueprints.json` is synthetic and byte-identical in both SDK repositories.
It covers the real SDK transport with mocked responses, not deployed server behavior.

Person 1/API owner must provide the deployed candidate and authorized synthetic workspace,
saved Blueprint and version. Run both examples normally and streaming with pinned version
and explicit latest. Record resolved references, request IDs, date and results; verify
invalid credentials, missing/foreign versions, insufficient scope and unsupported routes.
Complete the API isolation/billing gates, obtain SDK-maintainer review and verify API
production rollout before enabling clients. Then update AI Studio Docs (cURL, Python,
Node.js), bump the package version using RELEASING.md, and publish. No release is made here.
