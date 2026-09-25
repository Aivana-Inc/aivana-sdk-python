# aivana

Python client for the [Aivana Intelligence API](https://github.com/Aivana-Inc/aivana-sdk-python).

Requires Python 3.10 or newer. Built on `httpx`, with sync, async, and streaming
interfaces.

## Install

```bash
pip install aivana
```

## Quick start

Configuration is module-level, Stripe-style:

```python
import aivana

aivana.api_key = "ai_live_xxx"

res = aivana.generate("Should we enter the EU market in 2027?")
print(res.answer)
```

Your API key is the only required setting. `aivana.api_key = ...` and
`aivana.set_api_key(...)` are equivalent.

`api_base` defaults to the hosted API at `https://developers.aivana.ai`, the same
default as `@aivana/sdk`. Point it elsewhere only to run against your own
deployment:

```python
aivana.set_api_base("http://localhost:8088")   # local engine
```

## Command line

The package also installs an `aivana` command. To use it without adding the SDK
to a project, install it as a standalone tool:

```bash
pipx install aivana        # or run it without installing: uvx aivana "..."
export AIVANA_API_KEY=ai_live_xxx
aivana "Should we enter the EU market in 2027?"
```

The answer streams to stdout as it is written; progress, the trace and errors go
to stderr. So `aivana "..." > answer.md` saves just the answer, and the command
works in pipes. Text piped in is sent ahead of the question:

```bash
git diff | aivana "Review this change" --effort high
aivana "Summarise the three biggest risks" < contract.txt
aivana "What's driving the dip in this chart?" --image chart.png
aivana "Postgres or DynamoDB for a write-heavy API?" --shape tradeoffs --trace
aivana "Extract the invoice number and total" --shape extract --json < invoice.txt
```

Every option maps to one the SDK already has:

| option | SDK equivalent |
|---|---|
| `--effort auto\|low\|medium\|high` | `effort` |
| `--shape SHAPE` | `output_shape` |
| `--web` / `--no-web` | `web_search=True` / `False`; neither lets Aivana decide |
| `--system TEXT` | `system` |
| `--assistant-name NAME` | `assistant_name` |
| `--max-tokens N` | `max_tokens` |
| `--temperature T` | `temperature` |
| `--image PATH` (repeatable) | `attachments` |
| `--trace` | `intelligence_trace=True`, printed to stderr |
| `--json` | the whole `GenerateResponse` as JSON, without streaming |

As in the SDK, there is deliberately no option to choose a model or provider.
`AIVANA_API_BASE` points the command at another deployment, like
`set_api_base()`; `python -m aivana` runs the same program.

The Node CLI (`npm install -g @aivana/cli`) installs a command with the same name,
and both must behave identically. That is enforced by a shared conformance suite,
[`conformance/cli.json`](conformance/cli.json), which each implementation runs in
its own tests.

Scripts can branch on the exit code:

| code | meaning |
|---|---|
| 0 | success |
| 1 | the request failed |
| 2 | bad usage |
| 3 | authentication problem: no key, or an invalid or expired one |
| 4 | rate limited: wait, then retry |
| 5 | out of credits: top up in AI Studio |
| 6 | temporary failure (network, timeout, upstream): safe to retry |
| 130 | interrupted |

Two things worth knowing:

- **The key comes from `AIVANA_API_KEY` only.** There is no `--api-key` flag, on
  purpose: a key typed as an argument is saved in your shell history and is
  visible to other users in the process list.
- **Quote the question.** Unquoted words work, but the shell acts on characters
  such as `?`, `*` and `'` before `aivana` sees them. `aivana ask "..."` is the
  same as `aivana "..."`, for a question that starts with a word the CLI keeps
  for future commands (`chat`, `usage`, ...).

## Streaming

```python
async for chunk in aivana.generate_stream("Explain the CAP theorem"):
    print(chunk.delta, end="")
```

## Async

```python
res = await aivana.generate_async("Summarise our Q3 churn drivers.")
```

## Conversation history

Aivana is stateless — it never stores your conversations. To ask a follow-up you
send the prior turns back with the next question. Two ways to do that.

**Let the SDK track it.** `Chat` keeps the history in memory and appends each turn:

```python
chat = aivana.Chat()
chat.send("We're choosing between Postgres and DynamoDB.")
chat.send("What changes if write volume triples?")   # remembers the above
chat.reset()                                         # start fresh
```

**Or manage it yourself** — which is what you want when the history lives in your
own database and spans processes, requests or machines:

```python
messages = [
    {"role": "user",      "content": "We're choosing between Postgres and DynamoDB."},
    {"role": "assistant", "content": previous_answer},
    {"role": "user",      "content": "What changes if write volume triples?"},
]

res = aivana.generate(messages=messages)
```

Pass `messages` **instead of** a prompt — the last `user` message is the current
question. Each item is `{"role": ..., "content": ...}` in chronological order, with
role `"user"`, `"assistant"` or `"system"`.

A `"system"` message is lifted into the `system` field for you, so these are
equivalent:

```python
aivana.generate(messages=[{"role": "system", "content": "Answer in bullets."},
                          {"role": "user", "content": "Why did latency spike?"}])

aivana.generate("Why did latency spike?", system="Answer in bullets.")
```

If you pass **both**, the explicit `system` argument wins and the system message is
ignored — the two are never concatenated, because a merge order you cannot see is
worse than a rule you can.

### Follow-ups that refer back

For replies like "yes, do that" or "the second one", also pass `previous_intent`
and `pending_action` from the previous response. They are what let Aivana resolve
a bare "yes" against what was actually offered:

```python
first = aivana.generate("Should we migrate to DynamoDB?")

second = aivana.generate(
    messages=messages,
    previous_intent=first.intent.name,
    pending_action=first.pending_action,
)
```

`Chat` does this for you automatically — it is only manual history that needs it.

### Limits

| | current default |
|---|---|
| Messages per request | 40 |
| Characters per message | 200,000 |
| Characters per prompt | 200,000 |

History is re-sent on every turn and **billed every turn**, because nothing is
stored server-side. On a long conversation, trim or summarise old turns rather
than replaying all 40 — that is the single biggest lever on what a chat costs.

## Files and documents

**Only images can be attached.** `image/png`, `image/jpeg`, `image/webp`,
`image/gif` — up to 6 per request, 8 MiB each decoded.

PDF, Word and Excel files are **not** supported. Sending one raises
`InvalidRequestError` — the file is rejected, never silently ignored. The message
is deliberately terse ("request input was rejected"): it confirms the request was
the problem, but it does not name the offending type, so check the list above
rather than the error text.

To ask about a document, extract its text yourself and pass that as the prompt.
The extraction libraries below are not dependencies of this SDK — install
whichever you need:

**PDF** — `pip install pypdf`

```python
from pypdf import PdfReader
text = "\n".join(page.extract_text() or "" for page in PdfReader("report.pdf").pages)
```

**Word** — `pip install python-docx`

```python
from docx import Document
text = "\n".join(p.text for p in Document("contract.docx").paragraphs)
```

**Excel / CSV** — `pip install pandas openpyxl`

```python
import pandas as pd
text = pd.read_excel("q3.xlsx").to_markdown(index=False)
```

Then send the text as the prompt:

```python
res = aivana.generate(
    f"Summarise the three biggest risks in this document.\n\n{text}",
    system="Quote the passage each risk comes from.",
)
```

Two things worth doing:

- **Send text, not markup.** Stripped text costs far fewer tokens than raw HTML or
  XML, and answers are usually better for it.
- **Watch the size.** A long document can approach the 200,000-character prompt
  limit. For a large file, extract the relevant sections rather than the whole
  thing — and remember every character is billed.

A scanned PDF with no text layer extracts to nothing. Render those pages to PNG
and send them as image attachments instead.

## Options

Every option is optional, and every entrypoint — `generate`, `generate_async`,
`generate_stream`, `Chat` — accepts all of them as keyword arguments.

Omitting one is not a gap to fill in: it hands the decision to Aivana, which tunes
temperature, answer length and web search per question. Pass a value to override
that.

| option | type | default when omitted |
|---|---|---|
| `system` | str | no persona — Aivana's own voice |
| `assistant_name` | str | the assistant does not name itself |
| `web_search` | bool | Aivana decides from the question |
| `effort` | `"auto"`/`"low"`/`"medium"`/`"high"` | `"auto"` — Aivana decides |
| `temperature` | 0.0–2.0 | chosen per request |
| `top_p` | 0.0–1.0 | each model's own default |
| `stop_sequences` | list[str] | none — the answer ends naturally |
| `intelligence_trace` | bool | off — no trace is returned |
| `max_tokens` | int | sized to the question |
| `output_shape` | str | `"auto"` |
| `attachments` | list | none |
| `metadata` | dict | none |

## Choose how much intelligence to spend

`effort` is the one option that is about Aivana rather than about a model.
`temperature`, `top_p` and `max_tokens` shape how a model writes; `effort`
decides how much work goes into the answer in the first place.

```python
# A lookup you want back fast and cheap.
aivana.generate("What's the default port for Postgres?", effort="low")

# A decision you are going to act on.
aivana.generate(
    "Should we move billing off Stripe before the Series A?",
    effort="high",
)
```

| band | what happens | when to reach for it |
|---|---|---|
| `"auto"` | Aivana judges from the question | the default — leave it alone unless you know better than the question does |
| `"low"` | the fastest, cheapest path: one independent perspective | lookups, classification, formatting, anything with one right answer |
| `"medium"` | two independent perspectives, compared and reconciled | contested or subjective questions with a bounded blast radius |
| `"high"` | three or more perspectives | hard, high-stakes, open-ended questions |

Two things worth knowing:

- **It is a bound, not an instruction.** Aivana still reads the question and
  still decides how to answer it — `effort` only constrains how far it may go.
- **It is not a length control.** `"low"` does not mean "short"; use
  `max_tokens` for that. Cost scales roughly with the band, so `"high"` on a
  trivial question spends more for no gain — which is exactly the judgement
  `"auto"` exists to make.

## Give the assistant a persona

`system` is your own instructions — tone, format, domain, things to refuse:

```python
res = aivana.generate(
    "A customer wants a refund after 40 days.",
    system=("You are a support lead for a UK retailer. Answer in three short "
            "bullets. Cite the policy rule you applied. Never promise a refund "
            "outside policy."),
)
```

`assistant_name` sets the name it presents as:

```python
res = aivana.generate("Who are you?", assistant_name="Acme Copilot")
# → "I'm Acme Copilot..."
```

Use `assistant_name` rather than writing "your name is Acme" into `system`. A name
asked for inside a system prompt is only a request the model may or may not honour
— measured at roughly one time in three. `assistant_name` is substituted before the
model sees anything, so it always holds.

Two things to know:

**`system` is additive, not a replacement.** Aivana keeps its own instructions and
they win on conflict. You can shape persona, tone, format and domain focus — you
cannot use it to make Aivana reveal which underlying models produced an answer.

**Keep it short.** Aivana may re-send your system prompt internally more than once
while answering, so a long persona costs more tokens than its length suggests. The
8000-character limit is checked client-side, so an oversized prompt raises
`InvalidRequestError` before the request is sent.

## Web search

### Randomness: `temperature` or `top_p`, not both

Both control how varied an answer is; they just do it differently. `temperature`
reshapes the whole probability distribution, `top_p` narrows the pool to the most
likely tokens whose probabilities add up to your value.

```python
aivana.generate("Extract the invoice number", top_p=0.1)    # tight, predictable
aivana.generate("Ten campaign taglines", temperature=1.2)    # varied
```

Set **one** of the two. Sending both is accepted, but you are then steering the
same thing with two dials and the result is harder to reason about — and for some
questions Aivana cannot pass both through, in which case `top_p` wins and the
temperature is dropped for that call.

`top_p=0.0` is legal and is the most deterministic setting there is. Omitting the
option is **not** the same as `1.0`: omitted leaves the choice to Aivana.

### Stop sequences

Up to four strings. The answer ends where the first one appears, and the string
itself is not returned.

```python
aivana.generate("Answer, then stop.", stop_sequences=["###", "\n\nUser:"])
```

Useful when you are parsing the answer and know its end marker. Two things to
know: it shapes the output you receive, so it behaves the same on every question
— and the text past the marker is still generated and still billed, so this is not
a way to spend less.

### Intelligence Trace

Aivana decides how much intelligence each request needs. `intelligence_trace`
asks it to show its working.

```python
resp = aivana.generate(
    "Compare Postgres and DynamoDB for a write-heavy API.",
    intelligence_trace=True,
)

print(resp.trace["summary"]["route"])       # "2-model verification"
for step in resp.trace["steps"]:
    print(step["at_ms"], step["title"], "—", step["detail"])
```

```
1204 Understanding Request — Multi-part request with several considerations
1240 Fresh Data Check — Existing knowledge is sufficient; no live lookup needed
1255 Selecting Intelligence Path — A 2-model verification path would provide the most reliable answer
3980 Establishing Lead Perspective — Primary analysis generated
6310 Independent Perspectives — A second perspective independently analyzed the request
6402 Evaluating Perspectives — Perspectives agreed; the answer was confirmed rather than changed
8120 Final Synthesis — Findings combined into a single coherent answer
8155 Completed — Response delivered
```

The trace changes with the route. A simple question shows four steps and says
additional perspectives were unlikely to improve the answer; a question needing
current information shows the live-source lookup and the validation against what
came back. `trace["summary"]` carries the route, how many perspectives were
engaged, and whether fresh data was used; `trace["why_this_route"]` explains the
choice in plain sentences.

With `stream=True` the same information arrives as `trace` chunks while the
answer is being produced, so you can render the run as it happens:

```python
for chunk in aivana.generate("...", stream=True, intelligence_trace=True):
    if chunk.event == "delta":
        print(chunk.delta, end="")
    elif chunk.event == "trace" and "step" in chunk.data:
        step = chunk.data["step"]
        print(f"\n[{step['status']}] {step['title']}")
```

Each step arrives twice — once as it starts, once as it finishes — followed by a
single consolidated trace at the end.

The trace describes decisions and outcomes. It does not name the models that
answered, and it never exposes scoring, thresholds or prompts.

`web_search` has **three** states, and the third is the useful one:

```python
aivana.generate("What did the EU AI Act change in August?", web_search=True)
aivana.generate("Explain how quicksort works", web_search=False)
aivana.generate("Is our pricing still competitive?")          # Aivana decides
```

| value | behaviour |
|---|---|
| `True` | always search the web before answering |
| `False` | never search |
| *omitted* | Aivana judges whether the question depends on fresh data |

**Omitting it is not the same as `False`.** Omitted means "decide for me"; `False`
means "definitely don't". They are different requests.

On an API key the default is **off** — a search never happens unless you ask for
one, so it cannot turn up unannounced on your bill. Grounding costs extra tokens
and latency, so reach for `True` on current events, prices, releases, competitors
and anything else that dates; leave it off for reasoning, code, writing and
explanation, which do not improve with a web lookup.

## Temperature and length

```python
res = aivana.generate(
    "Draft a launch plan.",
    temperature=0.2,   # omit → chosen per request
    max_tokens=500,    # omit → sized to the question
)
```

`temperature` accepts `0.0`–`2.0`. Lower is more deterministic, higher more varied.

`max_tokens` is a **ceiling, not a target.** It can only shorten an answer — it
never raises the model-aware limit, so a very large value has no effect. When you
lower it, Aivana shortens what it aims to write rather than letting a full-length
answer get cut off mid-sentence.

## Recipes

**A support assistant that never searches the web.** Options passed to `Chat` apply
to every turn, so set the persona and the search policy once:

```python
support = aivana.Chat(
    assistant_name="Acme Support",
    system=("You are a support lead for Acme. Three bullets maximum. "
            "If the answer isn't in policy, say so and offer to escalate."),
    web_search=False,   # answers come from policy, not the open web
    temperature=0.2,    # consistent phrasing across tickets
)

support.send("Customer wants a refund after 40 days.")
support.send("They're now threatening a chargeback.")   # remembers the above
```

**A research assistant that always searches**, overridden per turn where it does
not need to:

```python
research = aivana.Chat(web_search=True)

research.send("What are the current enterprise pricing tiers for our competitors?")
research.send("Summarise that as a table", web_search=False)   # no lookup needed
```

Keyword arguments passed to `send()` win over the ones set on `Chat` for that turn.

**Structured output you can parse.** Combine a low temperature with `output_shape`:

```python
res = aivana.generate(
    transcript,
    output_shape="extract",
    temperature=0,
    system="Return only the fields asked for. Use null when a field is absent.",
)

print(res.structured)         # parsed dict, or None
print(res.structured_error)   # why parsing failed, if it did
```

**Streaming with a persona.** Options behave identically on the streaming calls:

```python
for chunk in aivana.generate(
    "Explain our outage to a customer.",
    stream=True,
    assistant_name="Acme Copilot",
    system="Plain language. No blame. Lead with impact, then the fix.",
    max_tokens=300,
):
    print(chunk.delta, end="", flush=True)
```

**Images.** Send a screenshot or diagram with the question:

```python
import base64

res = aivana.generate(
    "What's driving the dip in this chart?",
    attachments=[{
        "mime_type": "image/png",
        "data": base64.b64encode(open("chart.png", "rb").read()).decode(),
    }],
)
```

`data` takes raw base64 or a full data URL. Up to 6 images per request, 8 MiB each
decoded, in `image/png`, `image/jpeg`, `image/webp` or `image/gif`. Attachments
apply to the **current turn only** and are never replayed, so resend the image with
a follow-up about it.

## Errors

Every failure raises a subclass of `AivanaError`:

`AuthError` · `RateLimitError` · `InvalidRequestError` · `UpstreamError`

```python
from aivana import RateLimitError

try:
    aivana.generate("...")
except RateLimitError as err:
    backoff(err)
```

## License

Apache-2.0
