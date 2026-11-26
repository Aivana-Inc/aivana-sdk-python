# Saved Blueprint invocation

SDK support for running a saved Blueprint by id and version: the SDK portion of
[API #367](https://github.com/Aivana-Inc/aivana-intelligence-api/issues/367).

Create and save the Blueprint in your workspace first. Invocation uses its ID, an explicit version
and runtime input. Management from scoped API keys is a separate feature
([API #366](https://github.com/Aivana-Inc/aivana-intelligence-api/issues/366)).

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

## Examples

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

## Repeatable checks

```sh
python -m pip install . pytest build ruff==0.6.9
python -m pytest tests -q
python -m ruff check --select E9,F63,F7,F82 .
python -m build
```

`conformance/blueprints.json` is synthetic and byte-identical in both SDK repositories.
It covers the real SDK transport with mocked responses, not deployed server behavior.

## Before releasing a version

[blueprint-validation.md](blueprint-validation.md) records what has and has not been checked against a
real, deployed API. A maintainer releasing a version that includes these methods confirms, against the
environment being released:

- a saved synthetic Blueprint with two versions runs normally and streaming (and async), pinned and
  explicit `latest`, and the response names the resolved reference;
- a missing or foreign Blueprint is `blueprint_not_found`, bad credentials and a missing scope are
  refused, and an API without the routes raises `UnsupportedAPIError`, with no fallback to Generate;
- the API's isolation and billing behave as for the equivalent Generate request.

Then bump the package version and publish, following [RELEASING.md](../RELEASING.md).
