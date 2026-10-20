<!-- TARGET: Aivana-Inc/aivana-intelligence-api (no access from our account; fallback: aivana-sdk-python, ask to transfer)
     labels: bug or docs, OSU Developer Platform Team | finding F16 (Medium) - NEW 2026-10-20 -->
# effort="low" does not bound intelligence: same level, route and perspectives as effort="high"

Found during external-developer validation (aivana-sdk-python#15). The SDK and CLI send `effort` correctly (`PY-GEN-03`, `PY-CLI-12`).

## What happens
On the dev host, `effort="low"` and `effort="high"` produced identical Intelligence Trace summaries on every question tried. Both decision questions went to the top level, Premium, with 3 perspectives at `effort="low"`:

| Question | effort | intelligence_level | route | perspectives | latency | request id |
|---|---|---|---|---|---|---|
| What's the default port for Postgres? | low | Efficient | Efficient single-model | 1 | 4.6 s | `req_cdaaa2a73db13f0d89f22def` |
| ″ | high | Efficient | Efficient single-model | 1 | 2.2 s | `req_6540457bdf7a1d92c3375af0` |
| Should we enter the EU market in 2027? | low | **Premium** | Multi-model collaboration | **3** | 15.1 s | `req_3f66b584485de8b7c9383656` |
| ″ | high | Premium | Multi-model collaboration | 3 | 18.1 s | `req_aef82553ce00ac27a59c93aa` |
| Should we move billing off Stripe before the Series A? | low | **Premium** | Multi-model collaboration | **3** | 15.1 s | `req_e72fa085c0ca0d4d3ce57b60` |
| ″ | high | Premium | Multi-model collaboration | 3 | 21.6 s | `req_3009bdcf10330980bfc1b955` |

All with `intelligence_trace=True, max_tokens=60`, 2026-10-20, `dev-developers.aivana.ai`. Raw data: `results/run-2026-10-20/effort_probe.json`.

## Docs say
- Docs > Parameters / README: effort is "a ceiling on how much intelligence Aivana may apply"; "Low sets a lower reasoning ceiling and can reduce latency on simpler tasks".
- Docs > Intelligence Trace: "a lower effort bounds that judgement rather than replacing it." (It also says effort and level are "not a lookup table", but if `low` can still reach Premium, nothing is bounded.)
- README: the Stripe question is the example for `effort="high"`, and a Postgres lookup is the example for `"low"`.

## Why it matters
Developers choose `low` for latency and predictability. As observed, it changes neither. If this is intended, the docs overstate the control; if not, the ceiling isn't being applied (possibly only on the dev host).

## Questions for Aivana
1. Is `low` meant to exclude Premium (or multi-model routes)? If yes, this is a bug.
2. Is the dev host configured the same as production for effort handling?

Suite case: `PY-LIV-23` (live; asserts that `effort="low"` keeps the Stripe question below Premium).
