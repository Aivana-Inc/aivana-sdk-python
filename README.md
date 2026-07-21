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

aivana.set_api_key("aiv_live_xxx")
aivana.set_api_base("https://developers.aivana.ai")

res = aivana.generate("Should we enter the EU market in 2027?")
print(res.answer)
```

`api_base` defaults to `http://localhost:8088` for local development — point it at
your deployment when running against a real environment.

## Streaming

```python
async for chunk in aivana.generate_stream("Explain the CAP theorem"):
    print(chunk.delta, end="")
```

## Async

```python
res = await aivana.generate_async("Summarise our Q3 churn drivers.")
```

## Multi-turn chat

`Chat` retains the message history across turns:

```python
chat = aivana.Chat()
chat.send("We're choosing between Postgres and DynamoDB.")
chat.send("What changes if write volume triples?")
chat.reset()
```

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
