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

aivana.api_key = "aiv_live_xxx"

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
| `temperature` | 0.0–2.0 | chosen per request |
| `max_tokens` | int | sized to the question |
| `output_shape` | str | `"auto"` |
| `attachments` | list | none |
| `metadata` | dict | none |

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
