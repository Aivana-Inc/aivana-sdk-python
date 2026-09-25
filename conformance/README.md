# `aivana` CLI conformance suite

`cli.json` is the behaviour spec for the `aivana` command. There are two
implementations, and both install a command with that name, so a developer must
get the same answer, the same messages and the same exit codes whichever one they
have. Each runs every scenario in this file:

| implementation | install | runner |
|---|---|---|
| Python, in `aivana-sdk-python` | `pipx install aivana` | `tests/test_conformance.py` |
| Node, in `aivana-sdk-node` | `npm install -g @aivana/cli` | `test/conformance.test.mjs` |

A scenario is: arguments, environment, piped input and files, then a scripted
API response, then the exit code, stdout, stderr and HTTP request that must
result. The runners fake only the network. Everything above it (argument
parsing, the SDK's request body, its stream parser and error mapping, the
terminal output) is the real code.

What is **not** here: behaviour that depends on the platform rather than the
contract, such as real pipes and terminals, the progress line, signals and closed
pipes. Each repository tests those in its own suite.

## Changing the suite

The two files must stay byte-identical. `aivana-sdk-python` holds the canonical
copy.

1. Edit `conformance/cli.json` in `aivana-sdk-python` and bump `version` for any
   change in behaviour.
2. Copy it, unchanged, to `conformance/cli.json` in `aivana-sdk-node`.
3. Make both runners pass, and land the two pull requests together.

A scenario that one implementation cannot pass is a bug in that implementation,
or a sign the behaviour belongs in that repo's own tests. It is never a reason
for the copies to differ.

## Format

```jsonc
{
  "suite": "aivana-cli",
  "version": 1,
  "defaults": { "env": {...}, "stdin": null, "response": {...} },
  "scenarios": [ { "name": "...", "argv": [...], "expect": {...} } ]
}
```

Scenario fields. Anything omitted takes its value from `defaults`.

| field | meaning |
|---|---|
| `name` | unique; the test id |
| `argv` | arguments after `aivana`. `{tmp}` becomes the scenario's temporary directory |
| `env` | merged over the defaults; `null` unsets a variable |
| `stdin` | `null`: an interactive terminal with nothing piped. A string: piped text, then end of input |
| `files` | `name: base64` files to create in `{tmp}` first |
| `response` | what the fake API answers. See below |

`response` is one of:

| shape | meaning |
|---|---|
| `{"status": 200, "events": [[event, data], ...]}` | an SSE stream, as `/v1/generate:stream` sends it |
| `{"status": N, "json": {...}}` | a JSON body: an error envelope, or the `/v1/generate` response |
| `{"network_error": "connect"}` / `"timeout"` | the connection fails before any response |
| `{..., "then": "disconnect"}` | the stream's events, then the connection drops |

`expect` fields. Only the ones present are checked.

| field | check |
|---|---|
| `exit` | the exit code (required) |
| `stdout`, `stderr` | exact text |
| `stdout_contains`, `stderr_contains` | every string appears |
| `stdout_excludes`, `stderr_excludes` | no string appears |
| `stdout_starts_with` | a prefix |
| `stdout_json` | stdout parses as JSON and has these top-level values |
| `stderr_counts` | `{text: n}`: each text appears exactly `n` times |
| `requests` | how many HTTP requests were made |
| `request.url` | the full URL of the last request |
| `request.headers` | these headers, lowercase names |
| `request.body` | these top-level values in the JSON body |
| `request.body_keys` | exactly these top-level keys, sorted |

The placeholder `{request_source}` in an expected value stands for the
implementation's own tag (`cli-python`, `cli-node`), which it sends as
`metadata.request_source`.
