"""Docs parity: every Python example a developer can copy is run against the installed SDK.

Sources, as a developer meets them:
  README  the package's long description as published on PyPI (importlib.metadata), i.e. the
          README of the installed release, not whatever is on GitHub main.
  Docs    AI Studio > Docs (aivana-ai-studio src/data/docsData.ts and docsPagesV2.ts). Set
          AIVANA_STUDIO_REPO to the checkout; default: an aivana-ai-studio checkout next to this suite or next to the SDK repo.
          Without one, only the README examples run.

Examples on one page build on each other (configure, then generate, then read the response),
so a page's examples run in order in one shared namespace, as if pasted into one file.
The network is mocked (respx) with responses shaped like the real API's, so this costs nothing:
what it proves is that each example uses names, parameters and response fields the SDK has.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import importlib.metadata
import io
import json
import os
import re
import textwrap
from pathlib import Path

import httpx
import pytest
import respx

import aivana

from conftest import OFFLINE_BASE

def _find_studio() -> Path:
    """AIVANA_STUDIO_REPO, else an aivana-ai-studio checkout beside this suite or beside the SDK repo."""
    if os.environ.get("AIVANA_STUDIO_REPO"):
        return Path(os.environ["AIVANA_STUDIO_REPO"])
    here = Path(__file__).resolve()
    for parent in here.parents[1:4]:
        if (parent / "aivana-ai-studio" / "src" / "data").is_dir():
            return parent / "aivana-ai-studio"
    return here.parents[2] / "aivana-ai-studio"


STUDIO = _find_studio()


# ------------------------------------------------------------------ extraction

def _ts_python_blocks(path: Path):
    """(page slug, line, code) for every `language: "python", code: `...`` in a docs data file."""
    text = path.read_text(encoding="utf-8")
    for m in re.finditer(r'language:\s*"python"\s*,\s*code:\s*`', text):
        i, buf = m.end(), []
        while text[i] != "`":
            if text[i] == "\\":
                buf.append(text[i + 1])
                i += 2
                continue
            buf.append(text[i])
            i += 1
        slugs = re.findall(r'\bslug:\s*"([^"]+)"', text[:m.start()])
        yield (slugs[-1] if slugs else "?"), text.count("\n", 0, m.start()) + 1, "".join(buf)


def _snippets():
    out = []
    readme = importlib.metadata.metadata("aivana").get_payload() or ""
    for n, code in enumerate(re.findall(r"```python\n(.*?)```", readme, re.S), 1):
        out.append(("README", f"README (PyPI) block {n}", code))
    for name in ("docsData.ts", "docsPagesV2.ts"):
        f = STUDIO / "src" / "data" / name
        if f.exists():
            for slug, line, code in _ts_python_blocks(f):
                out.append((f"docs/{slug}", f"/docs/{slug} ({name}:{line})", code))
    return out


SNIPPETS = _snippets()


def _case_id(page: str) -> str:
    return "PY-DOC-README" if page == "README" else "PY-DOC-" + page.split("/", 1)[1].upper()


PARAMS = [pytest.param(page, where, code, id=where,
                       marks=pytest.mark.case(_case_id(page), "Docs parity",
                                              f"Every Python example on {page} runs against the installed SDK"))
          for page, where, code in SNIPPETS]


# ------------------------------------------------------------------ fake API

def _value_for(schema: dict):
    t = schema.get("type")
    if isinstance(t, list):                     # e.g. ["string", "null"]
        t = next((x for x in t if x != "null"), "null")
    if "enum" in schema:
        return schema["enum"][0]
    if t == "object" or "properties" in schema:
        return {k: _value_for(v) for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return [_value_for(schema.get("items") or {})]
    return {"string": "x", "integer": 1, "number": 1.5, "boolean": True}.get(t, "x")


TRACE = {"status": "completed",
         "steps": [{"id": "understanding", "title": "Understanding Request", "detail": "Single question",
                    "status": "ok", "at_ms": 900}],
         # summary keys as the live dev API returned them on 2026-10-20
         "summary": {"intelligence_level": "Advanced", "route": "2-model verification", "perspectives": 2,
                     "fresh_data": "not_required", "elapsed_ms": 9000, "complexity": "Medium",
                     "sources_used": None},
         "why_this_route": ["A second perspective was worth it"]}


def _generate(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    resp = {"id": "gen_doc", "request_id": "req_doc", "answer": "An answer.",
            "intent": {"name": "direct_chat", "confidence": 0.9, "signal": ""},
            "models_used": ["aivana-mmi"], "latency_ms": 500, "finish_reason": "stop", "notices": [],
            "usage": {"input_tokens": 10, "output_tokens": 5, "cached_tokens": 0, "credits": 0.0001}}
    if body.get("intelligence_trace"):
        resp["trace"] = TRACE
    rf = body.get("response_format") or {}
    if rf.get("type") == "json_schema":
        schema = (rf.get("json_schema") or {}).get("schema") or rf.get("schema") or {}
        resp["structured"] = _value_for(schema)
        resp["answer"] = json.dumps(resp["structured"])
    if body.get("output_shape") == "extract":
        resp["structured"] = {"field": "value"}
    return httpx.Response(200, json=resp)


def _stream(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    events = [("stage", {"stage": "Selecting the right intelligence"}),
              ("delta", {"text": "An "}), ("delta", {"text": "answer."})]
    if body.get("intelligence_trace"):
        events.append(("trace", TRACE))
    events.append(("done", {"finish_reason": "stop",
                            "usage": {"input_tokens": 10, "output_tokens": 5, "credits": 0.0001}}))
    sse = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events)
    return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=sse.encode())


# ------------------------------------------------------------------ the test

_namespaces: dict[str, dict] = {}

# What a reader is assumed to bring to an example, so a fragment can run:
#  - `import aivana`: a Docs page with one example assumes the Quickstart's setup;
#  - the placeholders README examples name for the reader's own data.
READER_CONTEXT = {
    "previous_answer": "Postgres if you need joins; DynamoDB for predictable key lookups.",
    "messages": [{"role": "user", "content": "We're choosing between Postgres and DynamoDB."}],
    "transcript": "Call with ACME on 3 Oct. Budget $40k. Decision by Friday.",
}


@pytest.fixture(scope="module", autouse=True)
def _docs_env(tmp_path_factory):
    """A developer's machine: key exported, a scratch folder with the files examples open."""
    work = tmp_path_factory.mktemp("docs")
    for name in ("contract.pdf", "report.pdf", "invoice.pdf", "chart.png", "image.png", "photo.jpg",
                 "data.csv", "notes.docx", "screenshot.png"):
        (work / name).write_bytes(b"%PDF-1.4 placeholder" if name.endswith(".pdf") else b"\x89PNG placeholder")
    old_cwd, old_key = os.getcwd(), os.environ.get("AIVANA_API_KEY")
    os.chdir(work)
    os.environ["AIVANA_API_KEY"] = "ai_test_docs_snippet_not_real"
    yield
    os.chdir(old_cwd)
    if old_key is None:
        os.environ.pop("AIVANA_API_KEY", None)
    else:
        os.environ["AIVANA_API_KEY"] = old_key


@pytest.mark.skipif(not SNIPPETS, reason="no examples found")
@pytest.mark.parametrize("page,where,code", PARAMS)
def test_example_runs(sdk_state, page, where, code):
    aivana.set_api_base(OFFLINE_BASE)
    ns = _namespaces.setdefault(page, {"__name__": "__docs__", "aivana": aivana, **READER_CONTEXT})
    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/v1/generate:stream$").mock(side_effect=_stream)
        mock.post(url__regex=r".*/v1/generate$").mock(side_effect=_generate)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            # Dedent (a block inside a Markdown list is indented) and allow a top-level
            # `await` / `async for`, which the async examples show as a fragment.
            compiled = compile(textwrap.dedent(code), where, "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            result = eval(compiled, ns)
            if asyncio.iscoroutine(result):
                asyncio.run(result)
