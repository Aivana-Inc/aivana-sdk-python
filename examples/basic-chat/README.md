# Basic AI Chat (Python)

A small browser chat application using the **released `aivana` Python SDK 0.4.0**.
Send a message, get an Aivana answer, then ask a follow-up. The API key stays on the
Python server. There is no frontend build step, account system or database.

It is the Python companion to the
[Node starter](https://github.com/Aivana-Inc/aivana-sdk-node/tree/main/examples/basic-chat) and shares its
page file for file, so the two look and behave the same in the browser. Only the server differs.
Tracked in [Python SDK #24](https://github.com/Aivana-Inc/aivana-sdk-python/issues/24).

## Standalone download (no Git required)

Download the approved `aivana-basic-chat-python.zip` release and extract it into a new
folder. Requires Python 3.10+. Open a terminal in that folder and run:

```sh
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m basic_chat setup
```

Setup creates a private `.env` without overwriting an existing one. Open `.env` in
your editor and add your own API key. Then:

```sh
python -m basic_chat doctor
python -m basic_chat
```

Open http://127.0.0.1:3006. Doctor checks local configuration and dependencies without
sending a paid request; it cannot verify your key or balance. Stop with Ctrl+C.

For updates, extract the new release into a new folder, run setup/install, and copy your
local `.env` yourself. Keep any application changes in your own Git repository and review
them when upgrading. To uninstall, remove the extracted folder (including its local key
file) after saving your own work.

Release maintainers generate this download with
`python tools/package_starter.py NEW_OUTPUT_DIRECTORY` from the SDK repository, then zip the folder.
Only an explicit file allowlist is copied; the package never includes `.env`, a private Blueprint,
tests, caches or Git history. `MANIFEST.json` records file checksums. A package is not a public
release until maintainers publish it.

## Use an Agent Kit blueprint

Design and test a text assistant in AI Studio's Agent Kit preview, then use
**Inspect / export Blueprint definition → Download definition JSON**. The starter does not
require the pending Blueprint storage or invocation backend.

1. Put the downloaded `blueprint-definition.json` in this folder, beside `requirements.txt`
   (not inside `public/`). Keep that filename. The server loads it automatically on startup.
2. Run `python -m basic_chat doctor` to validate it locally without making an API request.
3. Run `python -m basic_chat`, or stop and restart an already running server. Reload the
   browser. The page shows **Blueprint loaded**, its history behavior, and whether
   web search is allowed.
4. Send a question related to the assistant you configured. Generation uses the
   API key and account credit from your local `.env`.

For a different filename, set `AIVANA_BLUEPRINT_FILE=./my-agent.json` in `.env`.
Relative paths are resolved from the starter folder, even when launched elsewhere;
absolute paths are also supported. Quote paths with spaces in `.env`.
An explicit missing/unreadable file or an invalid definition stops startup; it
never silently falls back to generic chat. If the variable is unset and the
conventional file is absent, the starter keeps its original default behavior.

**Give the Blueprint a name.** An Agent Kit export carries a *purpose* but no name (a Blueprint's name is
metadata that is deliberately kept out of the exported definition), so the welcome screen would otherwise
say "Chat with your Blueprint." To show your own, set `AIVANA_BLUEPRINT_NAME=Juniper Landscaping Assistant` in `.env`
and restart. It becomes the welcome title and the browser tab title. It is one plain line of up to 80
characters, shown as text (never as markup), and ignored, with a note from `doctor` and at startup,
when no Blueprint is loaded. Nothing about the export file changes.

**Try the included fictional business:** set the following in `.env`:

```dotenv
AIVANA_BLUEPRINT_FILE=blueprints/landscaping.example.json
```

Then run doctor/start and ask “What services do you offer?” followed by “Help me
prepare an estimate request for the second service.” The sample supplies fictional
service facts and explicitly has no booking or submission integration. Replace
it with your own Agent Kit export to use your own instructions.

The JSON is a local snapshot. Re-export, replace the file, restart, and reload to
apply changes. It does not synchronize with Studio, call a saved Blueprint ID,
carry a display name/version, or create server-side conversation storage. Purpose
is descriptive metadata and is never inserted into the system instructions.

| Export setting | Starter behavior |
| --- | --- |
| System, Effort, Web Search Allowed | Applied to every Generate request using documented SDK options. |
| Temperature, Top-P, Max Tokens | Preserved, including zero. Null leaves the field out so the engine chooses its default; the starter's 800-token default is not added to an imported blueprint. Temperature and Top-P cannot both be set. |
| Stop sequences | Preserved exactly; empty arrays are omitted. |
| Text response format | Supported. JSON Schema (Strict) and other formats are rejected with instructions to explicitly choose Text and re-export. |
| Conversation history: session | The starter's bounded recent turns and continuation context are sent with follow-ups. |
| Conversation history: none | Earlier turns remain visible in this tab, but neither prior messages nor continuation context are sent. The server enforces this even if a browser submits them. |
| Knowledge / Sources | Absent or null only. Source references are rejected; no business-document retrieval is claimed. |

Validation follows the approved definition fields and bounds, refuses unknown
fields and coercion (a number must be a number, `true` is not `1`, `NaN` is not valid JSON), and limits the
compact definition to 64 KiB (file size up to 256 KiB including formatting). No imported file is executed.
The browser receives only a few behavior flags; instructions and file paths are not served or logged.
`blueprint-definition.json` is ignored by Git and excluded from the downloadable
package. Keep custom-named private exports out of your own Git commits too.

## Start from a fresh clone

Requires **Python 3.10 or newer** and an active Aivana API key with available usage credit.

```sh
git clone https://github.com/Aivana-Inc/aivana-sdk-python.git
cd aivana-sdk-python/examples/basic-chat
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m basic_chat setup       # creates a private .env; never overwrites one
```

Open `.env` in your editor and fill in `AIVANA_API_KEY`. Get a key from
[AI Studio API Keys](https://developers.aivana.ai/api-keys); see
[the key guide](https://developers.aivana.ai/docs/api-keys) and
[Quickstart](https://developers.aivana.ai/docs/quickstart). Keep `.env` local:
it is ignored by Git. Never paste your key into the browser, chat messages, or a report.

```dotenv
AIVANA_API_KEY=YOUR_ACTIVE_KEY
AIVANA_API_BASE=
PORT=3006
```

Leave `AIVANA_API_BASE` blank to use the SDK's production default,
`https://api.aivana.ai`. An approved development key needs its matching API
environment, for example `https://dev-developers.aivana.ai`. A test key is not a free
sandbox: real generation uses the account's credit.

```sh
python -m basic_chat
```

Open **http://127.0.0.1:3006**. Enter a message and press Send. Ask a follow-up, use
Stop to stop the answer, or New chat to reset. Enter inserts a new line;
Ctrl+Enter / Command+Enter sends. Change `PORT` if 3006 is already occupied.
Restart after editing `.env`. Variables already set in your shell override that file.

## What the starter shows

The page is the same one the Node starter shows, so everything below is also true there.

**Live answers.** By default the answer streams in with the SDK's `generate_stream()`. "Thinking…" shows until the first text arrives, then the answer fills in; Stop stays available the whole time and takes the place of Send. The API delivers text in a few large pieces, so the page **types it out** rather than letting it jump: text that has arrived is revealed a little each frame, by words, quickly while far behind and gently when nearly caught up (about a second for a typical answer, and a slow stream is simply followed as it arrives). An unfinished **bold**, ~~strike~~, `code` or [link](address) is never shown half-typed: it appears as one unit once its end has arrived (held back at its start meanwhile, for a bounded time, never inside fenced code, and released when the stream completes), so you do not see raw markers flash. The finished answer is saved and the toolbar appears once the typing has caught up. Stop and New chat end it at once; Stop keeps everything that had arrived. People who prefer reduced motion see the text immediately, and with streaming off there is no animation because the whole answer is already here. The pacing lives in `public/typing.mjs` (`TYPING`: minimum speed and catch-up rate). Turn streaming off in Settings to compare the whole-response behavior.

**Formatted answers.** Replies are rendered as Markdown: headings, lists, tables, links, inline code and fenced code blocks with syntax colors (JavaScript/TypeScript, JSON, Python, shell, CSS, SQL, YAML and HTML; any other language is shown as plain text). Each code block has its own **Copy** button. Nothing is ever inserted as HTML (see *Security of rendered answers* below).

**Actions under each answer.** **Copy** copies the answer's original Markdown, not the rendering. **Regenerate** (latest answer only) replaces that answer with a new one using your current settings. It sends a **new request that uses credit**, and says so next to the button. If the server refuses it, the earlier answer comes back.

**Following the answer.** The page follows new text while it streams. Scroll up to read earlier messages and it stops following; a **Jump to latest** button appears. The message box stays in place while only the conversation scrolls.

**When a response does not finish.**
- *Interrupted* (the stream failed partway): the text that had arrived stays on screen, labelled **Interrupted**, with a **Retry** button. Retry sends the same message again as a **new request that uses credit**; it is never done automatically.
- *Stopped* (you pressed Stop): the text that had arrived stays on screen, labelled **Stopped**.
- Either way the partial answer is **not** added to the conversation and is not sent with your next message. Your next message or **New chat** clears it. Work the API already accepted may still use credit.

**Settings.** Settings is closed during normal chat. Open it to choose *Intelligence effort* (Auto, Low, Medium, High: a ceiling on reasoning, not a length or price control), *Answer length* (the maximum output tokens, not a guaranteed length), *Web search* and *Live streaming*, each with a short explanation. The choices are validated on the server and are not saved. When an Agent Kit Blueprint is loaded its effort, length and web-search values are shown **read-only** as set by the Blueprint, so the starter cannot silently override it.

**Session details.** After a request completes, a small disclosure shows the input tokens, output tokens and response time **only if the API response included them**. It never shows cost or credits, models or internals.

### First-run verification

1. Run `python -m basic_chat setup`, then `python -m basic_chat doctor`. Doctor checks configuration without making a paid request.
2. Start the app, send a short prompt, and confirm that "Thinking…" turns into text that appears incrementally, with Stop available throughout.
3. Ask for a table and a code block (the starter's prompts do), then use Copy on the answer and on the code block and paste to confirm they match.
4. Ask a follow-up to verify conversation context. Switch streaming off and send another prompt to verify non-streaming mode.
5. Try effort and web-search settings only if you have sufficient credits. Press Stop, and confirm the partial text stays, is labelled Stopped, and is not sent with your next message.
6. For automated two-turn live verification, run `python -m basic_chat verify-live --billable` (uses account credit).

## How it works

```text
Browser (plain HTML, CSS and JavaScript)
  → POST /api/chat/stream (or /api/chat) on the local Python app (FastAPI + uvicorn)
  → request guard: Host, Origin, JSON only, size and time limits, two at a time
  → the `aivana` SDK: generate_stream() (or generate_async()) with { messages, previous_intent, pending_action, ... }
  → Aivana Intelligence API
  → text, continuation context and token usage returned to this browser
```

| File | Responsibility |
| --- | --- |
| `basic_chat/__main__.py` | The commands: start (the default), `setup`, `doctor`, `verify-live`. Opens the port on loopback. |
| `basic_chat/config.py` | Validate the server-only key, API origin, local port and the optional Blueprint name. |
| `basic_chat/guard.py` | The request guard (a small ASGI middleware): Host and Origin checks, body cap and time limit, concurrency cap, security headers. |
| `basic_chat/models.py` | The shape and limits of a chat request. Anything else is refused with a fixed sentence. |
| `basic_chat/app.py` | The routes; forward explicit conversation context; stream the answer; return a small answer envelope. |
| `basic_chat/errors.py` | Fixed public error messages. Nothing from the SDK or API is ever forwarded. |
| `basic_chat/client.py` | The one place the SDK is touched. |
| `basic_chat/blueprint.py` | Validate a local Agent Kit export and map its settings to SDK options. |
| `public/*` | The page: identical to the Node starter's (the repository's `FRONT_END.json` records which version). |

The starter uses the SDK's documented **explicit messages** pattern rather than one
shared `aivana.Chat` object. A global chat object on a web server would mix different
browsers' conversations. Only `user` and `assistant` history entries are accepted here;
API keys, system instructions, endpoints and generation controls are not browser inputs.

### Why it is built this way

You will likely copy parts of this into your own service, so the reasons are worth knowing.

- **FastAPI and uvicorn, with `async def` routes.** Pressing Stop closes the browser's connection. An async server
  can then cancel the call to Aivana at once, even while it is still waiting for the first word; a synchronous one
  cannot interrupt a call that is blocked waiting. The streaming route runs the SDK's stream in one task and cancels
  that task when the browser leaves, which closes the connection to Aivana and stops generation (and billing) for
  an answer nobody will read.
- **The guard is plain ASGI, not `BaseHTTPMiddleware`.** The latter wraps the response in its own stream, which sits
  between the browser and a streaming route. The guard only inspects the request and adds headers, so a hang-up
  reaches the route directly.
- **Versions are pinned, Starlette included.** How a hang-up cancels a streaming answer depends on how Starlette and
  uvicorn cooperate. `tests/test_stop.py` fails if an upgrade breaks it, so do not move `requirements.txt` without
  running the tests.
- **The SDK keeps one key per process** (`aivana.set_api_key`), so this starter serves one key. A multi-tenant
  service would pass a key per request.

### Security of rendered answers

An answer is untrusted text, so it is never turned into HTML. `markdown.mjs` parses it into
plain data and `render.mjs` builds the page with `createElement` and `textContent` only: no
`innerHTML`, no HTML parsing, no inline styles or scripts (the page's Content-Security-Policy
forbids them anyway). Raw HTML in an answer, such as `<script>` or `<img onerror=...>`, is shown as
literal text. Images are never loaded, so an answer cannot make your browser fetch an address.
A link survives only if it is a well-formed `http(s)` or `mailto` address; it opens in a new tab
with `noopener noreferrer`, and hovering shows its real destination. Parsing is bounded, so an odd or
hostile answer cannot slow the page.

SDK exceptions and upstream envelopes are not forwarded to the browser. Session details carry
only whole token counts and a response time.

## Conversation and usage boundaries

- History and continuation context live in browser memory only. This example writes
  no chat data to cookies, local/session storage, disk or a database. Separate tabs
  have separate histories. New chat, reload or closing the page clears this local history.
  This is the starter's storage behavior, not a statement about API retention.
- With session history enabled, each request sends up to **eight recent successful exchanges**, plus the current
  message, within a **24,000-character** context budget. Older exchanges are removed
  as whole pairs. New user messages are limited to 4,000 characters. These are this
  example's limits, not the platform's API limits. JSON requests are bounded to 256 KiB.
- Failed or stopped turns do not enter the next request's history. Failed messages
  remain in the composer for editing and manual resubmission.
- Without a blueprint, live web search is disabled and output is capped at 800 tokens.
  Imported blueprints use their own settings, which can increase credit use. The
  browser answer limit remains 16,000 characters; larger answers are rejected, not
  silently truncated. This is not a spending cap: repeated requests and repeated history consume
  account credit. The server allows at most two concurrent requests.
- Requests have a two-minute deadline. Stop, leaving the page and server shutdown
  cancel the call to Aivana. An accepted request may still use credit. The SDK waits and
  asks again only when Aivana refuses a request for a per-minute rate limit (at most
  twice, before any work or billing). A request Aivana may have accepted is never sent
  again automatically, including after a timeout, an interrupted stream or an uncertain
  network failure.
- The app serves a fixed list of public files, binds only to `127.0.0.1`, checks Host
  and Origin, and accepts only JSON chat requests. A request body must arrive within 15 seconds.
  It never serves `.env`, server source, installed packages, or arbitrary paths. No prompts,
  answers or keys are logged.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `ModuleNotFoundError` (fastapi, aivana, ...) | Activate the virtual environment and run `pip install -r requirements.txt`. |
| `No module named basic_chat` | Run the command from this folder (the one that contains `basic_chat/` and `requirements.txt`). |
| Blueprint validation fails | Check the specific field named in the terminal, choose supported settings in Agent Kit, and export again. Doctor makes no API call. |
| Blueprint changes do not appear | Check AIVANA_BLUEPRINT_FILE, replace the selected file, restart the server, and reload the browser. |
| Startup says the key is missing | Fill in `.env`, run from this folder, and restart. |
| "The local chat server could not start" | The port is in use or not allowed. Change `PORT` in `.env`. |
| Aivana rejected the key | Confirm the key is active and matches the configured API environment. Restart after changing it. |
| Access denied | Check key permissions and API environment. |
| Not enough credit | Check the account's Billing page in AI Studio. |
| Rate limit / server busy | Wait for the current requests to finish. Retry manually when ready. |
| Invalid request / oversized history | Shorten the message or choose New chat. |
| Timeout / temporary failure | Check network and [service status](https://status.aivana.ai). The result may be uncertain; no retry is made for you. |
| The browser cannot connect | Check the terminal, local port and the `127.0.0.1` address. This server is intentionally not reachable from other devices. |

Do not deploy this local example as a public shared service. Before hosting, add your
own authentication, per-user authorization and billing/usage limits, HTTPS, operational
monitoring, and an explicit conversation storage/retention policy. Keep credentials
server-side. Put a reverse proxy in front: uvicorn does not time out a client that never
finishes sending its request headers, which is harmless on loopback and not on the internet.
Accounts, persistence, attachments, RAG, Actions/MCP and publishing are outside this small
reference application.

## Repeatable verification

From this folder, with the virtual environment active:

```sh
pip install -r requirements-dev.txt
python -m pytest
ruff check .
```

The tests use fake credentials and a local stand-in for the API on loopback; they make no billed
calls. They run the real app under uvicorn and the real SDK, so they cover things that only exist on a
real connection: that Stop reaches the API call (before the first word, mid-answer, and on closing the tab),
that a stalled or oversized request is given up on, and that every slot is given back.

For a live check after installing/configuring the example, run:

```sh
python -m basic_chat verify-live --billable
```

This starts the app on a temporary loopback port and makes exactly **two small real
generation requests**: an initial synthetic question and a follow-up. It uses account
credit, prints no prompt, answer or key, and is never run by the tests or CI. It checks
that both requests return answers and that the follow-up recalls the synthetic nickname;
broader answer quality still needs human inspection.

### Keeping the page identical to the Node starter

`public/` is a byte-for-byte copy and is not edited here. `FRONT_END.json` records the checksum of every
file and the Node commit it came from; `tests/test_front_end.py` fails if any file differs or an extra one
appears. To take a change, make it in the Node starter, then run:

```sh
python tools/sync_front_end.py /path/to/aivana-sdk-node/examples/basic-chat/public
```

To also compare against a checkout of the Node repository, set `AIVANA_NODE_STARTER_DIR` to its
`examples/basic-chat` folder before running the tests. The scheduled workflow `front-end-drift.yml` does this every day
(it needs the repository secret `NODE_REPO_READ_TOKEN`, described at the top of that file, and fails rather than passes without it). The server rewrites one link in `index.html` (the footer's
"View source code") to point at this starter, and refuses to start if that link is not found exactly once.

**What is not tested here.** There is no browser test suite in this repository: the page's own behavior (typing
animation, keyboard use, accessibility, scrolling) is checked in the Node repository's `tools/browser-checks`, and the
page is identical. What belongs to this server, that Stop reaches the API call, is tested over real sockets in
`tests/test_stop.py`. Neither replaces a person trying the page on real devices and browsers.

Record the tested SDK version/environment and which checks were live versus fixture-based.
