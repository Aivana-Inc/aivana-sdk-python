"""`aivana` — ask the Aivana Intelligence API from a terminal.

    export AIVANA_API_KEY=ai_live_...
    aivana "Should we move billing off Stripe before the Series A?"
    git diff | aivana "Review this change" --effort high

A thin layer over this SDK: every request is an `aivana.generate()` call, the same
one an application makes, to the same public endpoint. What this module adds is
terminal behaviour (arguments, piped input, progress, exit codes) and nothing about
how an answer is produced, so it cannot drift from the SDK the way the old vendored
SDK copies drifted from the API.

It has no model, provider or mode option, deliberately. Like the SDK it offers
choices about the OUTCOME (effort, output shape, web search); which models answer
is Aivana's decision and is never selectable or shown.
"""
from __future__ import annotations

import argparse
import base64
import os
import select
import sys
from pathlib import Path
from typing import Any, Optional, Sequence, TextIO
from urllib.parse import urlsplit

import httpx

import aivana
from aivana.exceptions import (
    AivanaError,
    AuthError,
    ForbiddenError,
    InvalidRequestError,
    RateLimitError,
    UpstreamError,
)

# Exit codes. Scripts branch on these, so they are part of the interface: new ones
# may be added, existing ones are never renumbered.
EXIT_OK = 0
EXIT_FAILED = 1         # the request was rejected, or something unexpected broke
EXIT_USAGE = 2          # bad arguments (argparse's own convention)
EXIT_AUTH = 3           # no key, an invalid or expired key, or a key without access
EXIT_RATE_LIMITED = 4   # too many requests: wait, then retry
EXIT_NO_CREDIT = 5      # the balance is empty: retrying will not help, topping up will
EXIT_TEMPORARY = 6      # network, timeout or upstream failure: safe to retry
EXIT_INTERRUPTED = 130  # Ctrl-C (128 + SIGINT, the shell convention)

# Stored as `request_source` on every usage record, so CLI traffic can be told
# apart from SDK traffic with no server change. The engine never reads it.
REQUEST_SOURCE = "cli-python"

# The image types the API accepts, by file extension. The server's own rejection is
# deliberately terse ("request input was rejected") and never names the file, so
# this is the only place a caller can learn which attachment was the problem.
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# How long to wait for piped input to START when a question was also given. Past
# this the input is treated as absent, with a note, so a stdin that is open but
# never written to (an agent's shell tool, `ssh host aivana ...`, a subprocess that
# inherited its parent's pipe) cannot hang the command forever. Input that has
# started is always read to the end, however slowly it arrives.
STDIN_WAIT_S = 3.0

# Words held back for commands that may exist later (`aivana chat`, ...). Today they
# fail with a pointer to `aivana ask`, so shipping one turns an error into a feature
# instead of changing what an invocation someone already scripted does.
RESERVED_COMMANDS = ("chat", "configure", "login", "logout", "usage", "whoami")

# Mirrors GenerateRequest's enums. A value the API adds later is rejected here, and
# loudly, until it is added — never silently dropped.
EFFORTS = ("auto", "low", "medium", "high")
SHAPES = ("auto", "text", "recommendation", "summary", "tradeoffs", "decision", "extract")

# API field -> the flag a caller would fix, for per-field validation errors.
_FLAG_FOR_FIELD = {
    "prompt": "the question",
    "system": "--system",
    "assistant_name": "--assistant-name",
    "effort": "--effort",
    "output_shape": "--shape",
    "max_tokens": "--max-tokens",
    "temperature": "--temperature",
    "attachments": "--image",
}

DESCRIPTION = """\
Ask the Aivana Intelligence API from your terminal.

The answer streams to stdout. Progress, the trace and errors go to stderr, so
`aivana "..." > answer.md` saves just the answer. Text piped in is sent ahead
of the question.

examples:
  aivana "Should we migrate billing to DynamoDB?"
  git diff | aivana "Review this change" --effort high
  aivana "What's driving the dip in this chart?" --image chart.png
  aivana "Postgres or DynamoDB for a write-heavy API?" --shape tradeoffs --trace
  aivana "Extract the invoice number and total" --shape extract --json < invoice.txt
"""

EPILOG = """\
environment:
  AIVANA_API_KEY    your API key (required). Create one in AI Studio > API Keys.
                    It is read from the environment only: a key typed as an
                    argument would land in your shell history and process list.
  AIVANA_API_BASE   API address. Defaults to https://developers.aivana.ai

exit codes:
  0  success                     4  rate limited: wait, then retry
  1  request failed              5  out of credits: top up in AI Studio
  2  bad usage                   6  temporary failure: safe to retry
  3  authentication problem    130  interrupted
"""


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for the `aivana` command. Returns the process exit code."""
    args_in = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        _tolerate_unencodable(stream)

    if not args_in and _isatty(sys.stdin):
        _parser().print_help()
        return EXIT_USAGE
    if args_in[:1] == ["help"]:
        _parser().print_help()
        return EXIT_OK
    if args_in[:1] == ["ask"]:
        args_in = args_in[1:]
    elif args_in and args_in[0] in RESERVED_COMMANDS:
        _error(f"`aivana {args_in[0]}` is reserved for a future command.",
               f"To ask a question that starts with \"{args_in[0]}\", use:  "
               f"aivana ask {' '.join(args_in)}")
        return EXIT_USAGE

    try:
        # Intermixed, so options may sit anywhere among the question's words:
        # `aivana why is --effort high this slow` still reads the whole question.
        args = _parser().parse_intermixed_args(args_in)
    except SystemExit as exit_:         # --help, --version, or a usage error
        return exit_.code if isinstance(exit_.code, int) else EXIT_USAGE

    try:
        return _ask(args)
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
    except BrokenPipeError:
        # The reader went away (`aivana ... | head -3`). Point stdout at devnull so
        # the interpreter's own flush at exit doesn't print a second error.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass
        return EXIT_FAILED


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aivana",
        usage='%(prog)s [options] "QUESTION"\n       ... | %(prog)s [options] ["QUESTION"]',
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        # Abbreviations would let `--temp` mean --temperature today and turn
        # ambiguous the day a `--template` ships, breaking every script that used
        # it. Full option names only.
        allow_abbrev=False,
    )
    p.add_argument("question", nargs="*", metavar="QUESTION",
                   help="what to ask. Quote it so the shell passes it as one piece.")
    p.add_argument("--effort", choices=EFFORTS,
                   help="how much intelligence to spend. auto (the default) lets "
                        "Aivana judge from the question.")
    p.add_argument("--shape", dest="output_shape", choices=SHAPES, metavar="SHAPE",
                   help="answer format: " + ", ".join(SHAPES))
    p.add_argument("--web", dest="web_search", action=argparse.BooleanOptionalAction,
                   default=None,
                   help="--web always searches the web first, --no-web never does. "
                        "With neither, there is no search: the default for API keys.")
    p.add_argument("--system", metavar="TEXT",
                   help="your own instructions: persona, tone, format "
                        "(max 8000 characters)")
    p.add_argument("--assistant-name", metavar="NAME",
                   help="the name the assistant presents as")
    p.add_argument("--max-tokens", type=int, metavar="N",
                   help="a ceiling on answer length. It can shorten an answer, "
                        "never lengthen it.")
    p.add_argument("--temperature", type=float, metavar="T",
                   help="0.0-2.0. Omit to let Aivana choose per question.")
    p.add_argument("--image", action="append", default=[], metavar="PATH",
                   help="attach a PNG, JPEG, WebP or GIF image (repeatable)")
    p.add_argument("--trace", action="store_true",
                   help="show the Intelligence Trace: how Aivana handled the question")
    p.add_argument("--json", action="store_true",
                   help="wait for the whole response and print it as JSON "
                        "(no streaming)")
    p.add_argument("-q", "--quiet", action="store_true", help="no progress line")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {aivana.__version__}")
    return p


def _ask(args: argparse.Namespace) -> int:
    key = os.environ.get("AIVANA_API_KEY", "").strip()
    if not key:
        _error("no API key found.",
               "Create one in AI Studio > API Keys, then run:",
               "  export AIVANA_API_KEY=ai_live_...")
        return EXIT_AUTH
    aivana.set_api_key(key)
    base = os.environ.get("AIVANA_API_BASE", "").strip()
    if base:
        parts = urlsplit(base)
        # Without a scheme and host, every request would fail as a network error
        # that says nothing about the actual mistake.
        if parts.scheme not in ("http", "https") or not parts.hostname:
            _error("AIVANA_API_BASE must be a full URL, such as https://developers.aivana.ai")
            return EXIT_USAGE
        aivana.set_api_base(base)
        if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
            _note(f"AIVANA_API_BASE is plain http://, so your API key travels "
                  f"unencrypted to {parts.hostname}.")

    try:
        question = _read_question(args.question)
        attachments = [_attachment(path) for path in args.image]
    except ValueError as e:
        _error(str(e))
        return EXIT_USAGE
    if not question:
        _error("no question given.",
               'Pass one in quotes, e.g.  aivana "What changed in the EU AI Act?"',
               "or pipe text in, e.g.  cat notes.txt | aivana \"Summarize this\"")
        return EXIT_USAGE

    # Only what the caller chose reaches the SDK. An omitted option is not a
    # default to fill in: it hands that decision to Aivana (see the SDK README).
    chosen = {
        "system": args.system,
        "assistant_name": args.assistant_name,
        "effort": args.effort,
        "output_shape": args.output_shape,
        "web_search": args.web_search,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "attachments": attachments or None,
        "intelligence_trace": True if args.trace else None,
    }
    options: dict[str, Any] = {k: v for k, v in chosen.items() if v is not None}
    options["metadata"] = {"request_source": REQUEST_SOURCE}

    try:
        if args.json:
            return _ask_json(question, options, quiet=args.quiet)
        return _ask_streaming(question, options, quiet=args.quiet, trace=args.trace)
    except AivanaError as e:
        return _report_api_error(e, json_mode=args.json)
    except httpx.TimeoutException:
        _error("timed out waiting for Aivana.", "It is safe to retry.")
        return EXIT_TEMPORARY
    except httpx.TransportError as e:
        _error(f"couldn't reach {aivana.api_base} ({type(e).__name__}).",
               "Check your connection, or AIVANA_API_BASE if you set it. "
               "It is safe to retry.")
        return EXIT_TEMPORARY


def _read_question(words: Sequence[str]) -> str:
    question = " ".join(words).strip()
    piped = ""
    stdin = sys.stdin
    if stdin is not None and not _isatty(stdin):
        # With no question on the command line the piped text IS the question, so
        # waiting for it is right. With one, a silent stdin is far more often a
        # pipe nobody will write to than input that is merely slow to start.
        if question and not _input_starts(stdin, STDIN_WAIT_S):
            _note(f"no piped input arrived within {STDIN_WAIT_S:g}s, so only the "
                  "question was sent.",
                  "Nothing to pipe? Add  < /dev/null  to skip the wait. Slow "
                  "input? Save it to a file first and redirect that in.")
        else:
            try:
                piped = stdin.read().strip()
            except UnicodeDecodeError:
                raise ValueError("the piped input isn't text. Attach images with "
                                 "--image; for a PDF, extract its text first.") from None
    if piped and question:
        # The material first and the question after it: questions about long input
        # are answered better when they come last.
        return f"{piped}\n\n{question}"
    return piped or question


def _input_starts(stdin: Any, timeout: float) -> bool:
    """True once stdin has data waiting or has closed; False if it stays silent.

    Only POSIX can watch a pipe with `select`. Elsewhere, and for anything without
    a real file descriptor, this answers True and the read simply blocks.
    """
    if os.name == "nt":
        return True
    try:
        fd = stdin.fileno()
    except (AttributeError, OSError, ValueError):
        return True
    ready, _, _ = select.select([fd], [], [], timeout)
    return bool(ready)


def _attachment(path: str) -> dict[str, str]:
    suffix = Path(path).suffix.lower()
    mime = IMAGE_TYPES.get(suffix)
    if mime is None:
        if suffix == ".pdf":
            how = f'extract its text first, e.g.  pdftotext {path} - | aivana "Summarize this"'
        else:
            how = f'pipe it in instead, e.g.  aivana "Summarize this" < {path}'
        raise ValueError(f"{path}: only PNG, JPEG, WebP and GIF images can be "
                         f"attached. To ask about a document, {how}")
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise ValueError(f"{path}: {e.strerror or e}") from None
    return {"mime_type": mime, "data": base64.b64encode(data).decode("ascii")}


def _ask_streaming(question: str, options: dict[str, Any], *,
                   quiet: bool, trace: bool) -> int:
    out = sys.stdout
    progress = _Progress(sys.stderr, enabled=not quiet and _isatty(sys.stderr))
    trace_view = _TraceView(progress) if trace else None
    answering = False
    ends_with_newline = True
    finish_reason = "stop"
    failure: Optional[tuple[int, str]] = None
    try:
        for chunk in aivana.generate(question, stream=True, **options):
            if chunk.event == "stage":
                progress.show(str(chunk.data.get("stage") or ""))
            elif chunk.event == "delta" and chunk.delta:
                if not answering:
                    answering = True
                    progress.stop()
                    if trace_view is not None:
                        trace_view.answer_started = True
                out.write(chunk.delta)
                out.flush()
                ends_with_newline = chunk.delta.endswith("\n")
            elif chunk.event == "trace" and trace_view is not None:
                trace_view.feed(chunk.data)
            elif chunk.event == "error":
                failure = _stream_failure(chunk.data)
            elif chunk.event == "done":
                finish_reason = str(chunk.data.get("finish_reason") or "stop")
    except httpx.TransportError:
        if answering:
            _finish_line(out, ends_with_newline)
            _note("the connection dropped mid-answer, so the text above is incomplete.")
            ends_with_newline = True
        raise
    finally:
        progress.stop()
        if answering:
            _finish_line(out, ends_with_newline)

    if trace_view is not None:
        trace_view.finish(after_answer=answering)
    if failure is not None:
        code, message = failure
        _error(message + (" The text above is incomplete." if answering else ""))
        return code
    if finish_reason == "length":
        more = (" Raise --max-tokens to allow a longer one."
                if options.get("max_tokens") else "")
        _note(f"the answer was cut off at the length limit.{more}")
    return EXIT_OK


def _ask_json(question: str, options: dict[str, Any], *, quiet: bool) -> int:
    progress = _Progress(sys.stderr, enabled=not quiet and _isatty(sys.stderr))
    progress.show("Waiting for the complete answer")
    try:
        resp = aivana.generate(question, **options)
    finally:
        progress.stop()
    sys.stdout.write(resp.model_dump_json(indent=2) + "\n")
    return EXIT_OK


def _stream_failure(data: dict[str, Any]) -> tuple[int, str]:
    """An `error` frame inside a 200 stream: the engine could not finish."""
    kind = str(data.get("type") or "")
    if kind in ("upstream_error", "upstream", "timeout"):
        return EXIT_TEMPORARY, "Aivana couldn't complete this answer. It is safe to retry."
    if kind == "invalid_request":
        return EXIT_FAILED, ("the request was rejected. Check the question, "
                             "--system and any --image files.")
    return EXIT_FAILED, str(data.get("message") or "the request failed.")


def _report_api_error(e: AivanaError, *, json_mode: bool) -> int:
    hints: list[str] = []
    code = EXIT_FAILED
    if isinstance(e, AuthError):
        code = EXIT_AUTH
        hints += ["Create a new key in AI Studio > API Keys, then run:",
                  "  export AIVANA_API_KEY=ai_live_..."]
    elif isinstance(e, ForbiddenError):
        if e.code == "host_not_allowed":
            hints.append(f"Answers are only served from the developer API host, and "
                         f"{aivana.api_base} isn't it. Unset AIVANA_API_BASE to use "
                         f"https://developers.aivana.ai.")
        else:
            code = EXIT_AUTH
            hints.append("This key isn't allowed to generate answers. Create one "
                         "that is in AI Studio > API Keys.")
    elif isinstance(e, RateLimitError):
        code = EXIT_RATE_LIMITED
        hints.append("Wait a moment, then try again.")
    elif e.code == "insufficient_credit":
        code = EXIT_NO_CREDIT
        hints.append("Add credits in AI Studio > Billing.")
    elif isinstance(e, UpstreamError) or e.code in ("timeout", "config_unavailable"):
        code = EXIT_TEMPORARY
        if e.code == "timeout" and json_mode:
            hints.append("--json waits for the whole answer. Drop it to stream the "
                         "answer as it is written.")
        else:
            hints.append("It is safe to retry.")
    elif isinstance(e, InvalidRequestError):
        for detail in e.details:
            hints.append(f"{_field_name(detail.get('loc'))}: {detail.get('msg')}")
    request_id = f" (request id: {e.request_id})" if e.request_id else ""
    _error(f"{e.message}{request_id}", *hints)
    return code


def _field_name(loc: Any) -> str:
    parts = [str(p) for p in (loc or []) if p != "body"]
    if not parts:
        return "request"
    return _FLAG_FOR_FIELD.get(parts[0], ".".join(parts))


class _Progress:
    """One status line on stderr, rewritten in place ("Selecting the right
    intelligence…").

    Drawn only on an interactive terminal: redirected stderr gets none of it, so a
    log never fills up with half-overwritten lines.
    """

    def __init__(self, stream: TextIO, *, enabled: bool) -> None:
        self.stream = stream
        self._enabled = enabled
        self._label = ""
        self._width = 0

    def show(self, label: str) -> None:
        if not self._enabled or not label:
            return
        line = f"{label}…"
        # Padded to the previous width so a shorter label fully covers a longer one.
        self.stream.write("\r" + line.ljust(self._width))
        self.stream.flush()
        self._label, self._width = label, len(line)

    def clear(self) -> None:
        if self._width:
            self.stream.write("\r" + " " * self._width + "\r")
            self.stream.flush()
        self._label, self._width = "", 0

    def stop(self) -> None:
        """Clear the line for good. Nothing redraws once the answer is streaming."""
        self.clear()
        self._enabled = False

    def above(self, text: str) -> None:
        """Print lines that stay, keeping the status line (if any) below them."""
        label = self._label
        self.clear()
        self.stream.write(text + "\n")
        self.stream.flush()
        self.show(label)


class _TraceView:
    """The Intelligence Trace on stderr, kept out of the answer.

    Steps print as they finish while Aivana is still working. Once the answer starts
    streaming the rest are held and printed after it: on a terminal, stdout and
    stderr share one screen, and a step landing mid-answer would split a sentence.
    """

    _MARKS = {"ok": "✓", "skipped": "–", "failed": "✗"}

    def __init__(self, progress: _Progress) -> None:
        self._progress = progress
        self._shown: set[str] = set()
        self._held: dict[str, dict[str, Any]] = {}
        self._final: Optional[dict[str, Any]] = None
        self._header_done = False
        self.answer_started = False

    def feed(self, data: dict[str, Any]) -> None:
        if isinstance(data.get("steps"), list):     # the consolidated trace, sent last
            self._final = data
            return
        step = data.get("step")
        # A step arrives twice, starting and finished; only the finished one prints.
        if not isinstance(step, dict) or step.get("status") not in self._MARKS:
            return
        key = self._key(step)
        if key in self._shown:
            return
        if self.answer_started:
            self._held[key] = step
        else:
            self._emit([self._line(step)])
            self._shown.add(key)

    def finish(self, *, after_answer: bool) -> None:
        if self._final is not None:
            rest = [s for s in self._final["steps"]
                    if isinstance(s, dict) and s.get("status") in self._MARKS
                    and self._key(s) not in self._shown]
        else:
            rest = list(self._held.values())
        lines = [self._line(s) for s in rest] + self._summary()
        if lines and after_answer:
            lines.insert(0, "")
        self._emit(lines)

    def _emit(self, lines: list[str]) -> None:
        if not lines:
            return
        if not self._header_done:
            lines = ["Intelligence Trace", *lines] if lines[0] else \
                ["", "Intelligence Trace", *lines[1:]]
            self._header_done = True
        self._progress.above("\n".join(lines))

    def _summary(self) -> list[str]:
        final = self._final or {}
        summary = final.get("summary") or {}
        parts = []
        if summary.get("route"):
            parts.append(str(summary["route"]))
        count = summary.get("perspectives")
        if isinstance(count, int):
            parts.append(f"{count} perspective{'' if count == 1 else 's'}")
        if summary.get("fresh_data") == "enabled":
            sources = summary.get("sources_used")
            parts.append(f"live sources used ({sources})"
                         if isinstance(sources, int) else "live sources used")
        elif summary.get("fresh_data") == "not_required":
            parts.append("no live data needed")
        lines = [f"  Route: {' · '.join(parts)}"] if parts else []
        lines += [f"  · {why}" for why in final.get("why_this_route") or []]
        return lines

    @staticmethod
    def _key(step: dict[str, Any]) -> str:
        return str(step.get("id") or step.get("title") or "")

    @classmethod
    def _line(cls, step: dict[str, Any]) -> str:
        text = f"  {cls._MARKS[step['status']]} {step.get('title') or ''}"
        if step.get("detail"):
            text += f" — {step['detail']}"
        if isinstance(step.get("at_ms"), (int, float)):
            # Whole tenths, rounded half up, so every implementation prints the same
            # figure. Float formatting can't promise that: 1.25 rounds down in Python
            # and up in JavaScript, and 8.45 is stored as 8.4499... so both print 8.4.
            # The conformance suite pins 1250 ms to "1.3s" and 8450 ms to "8.5s".
            tenths = (int(step["at_ms"]) + 50) // 100
            text += f"  {tenths // 10}.{tenths % 10}s"
        return text


def _finish_line(out: TextIO, ends_with_newline: bool) -> None:
    if not ends_with_newline:
        out.write("\n")
        out.flush()


def _error(message: str, *hints: str) -> None:
    _stderr_lines(f"aivana: error: {message}", hints)


def _note(message: str, *hints: str) -> None:
    _stderr_lines(f"aivana: note: {message}", hints)


def _stderr_lines(first: str, rest: Sequence[str]) -> None:
    sys.stderr.write("\n".join([first, *(f"  {line}" for line in rest)]) + "\n")
    sys.stderr.flush()


def _isatty(stream: Any) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):     # no isatty, or already closed
        return False


def _tolerate_unencodable(stream: Any) -> None:
    """Replace, rather than crash on, characters the output can't encode.

    A Windows console or pipe on a legacy code page cannot encode every character
    an answer may contain (arrows, emoji, non-Latin scripts). Without this, one
    such character ends the program halfway through an answer.
    """
    try:
        stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


if __name__ == "__main__":
    sys.exit(main())
