"""The shared `aivana` CLI conformance suite, run against this implementation.

conformance/cli.json is the behaviour spec both CLIs must meet: this one, and the
Node CLI (@aivana/cli), which runs the same file. conformance/README.md has the
format and the rule for changing it: the two copies stay byte-identical.

    python3 -m pytest tests/test_conformance.py -q
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from cli_doubles import Stdin

from aivana import cli

SUITE_PATH = Path(__file__).resolve().parent.parent / "conformance" / "cli.json"
SUITE = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
SCENARIOS = SUITE["scenarios"]

EXPECT_KEYS = {
    "exit", "stdout", "stderr", "stdout_contains", "stderr_contains", "stdout_excludes",
    "stderr_excludes", "stdout_starts_with", "stdout_json", "stderr_counts", "requests",
    "request",
}
REQUEST_KEYS = {"url", "headers", "body", "body_keys"}
SCENARIO_KEYS = {"name", "argv", "env", "stdin", "files", "response", "expect"}


def test_the_suite_is_well_formed():
    """A typo in the suite must fail loudly, not quietly check nothing."""
    assert SUITE["suite"] == "aivana-cli"
    assert isinstance(SUITE["version"], int)
    names = [s["name"] for s in SCENARIOS]
    assert len(names) == len(set(names)), "scenario names must be unique"
    for s in SCENARIOS:
        assert set(s) <= SCENARIO_KEYS, (s["name"], set(s) - SCENARIO_KEYS)
        assert isinstance(s["argv"], list), s["name"]
        assert "exit" in s["expect"], s["name"]
        assert set(s["expect"]) <= EXPECT_KEYS, (s["name"], set(s["expect"]) - EXPECT_KEYS)
        assert set(s["expect"].get("request", {})) <= REQUEST_KEYS, s["name"]


def _fill(value: Any, tmp: Path) -> Any:
    """Replace the suite's placeholders in argv and expected values."""
    if isinstance(value, str):
        return value.replace("{tmp}", str(tmp)).replace("{request_source}", cli.REQUEST_SOURCE)
    if isinstance(value, list):
        return [_fill(v, tmp) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, tmp) for k, v in value.items()}
    return value


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_scenario(scenario, api, run, monkeypatch, tmp_path):
    defaults = SUITE["defaults"]
    for name, value in {**defaults["env"], **scenario.get("env", {})}.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    piped = scenario.get("stdin", defaults["stdin"])
    monkeypatch.setattr(sys, "stdin",
                        Stdin(tty=True) if piped is None else Stdin(piped, tty=False))
    for name, content in scenario.get("files", {}).items():
        (tmp_path / name).write_bytes(base64.b64decode(content))
    api.response = scenario.get("response", defaults["response"])

    code, out, err = run(*_fill(scenario["argv"], tmp_path))
    expect = _fill(scenario["expect"], tmp_path)
    shown = f"\n--- exit {code}\n--- stdout\n{out}\n--- stderr\n{err}"

    assert code == expect["exit"], f"exit code{shown}"
    if "stdout" in expect:
        assert out == expect["stdout"], f"stdout{shown}"
    if "stderr" in expect:
        assert err == expect["stderr"], f"stderr{shown}"
    for text in expect.get("stdout_contains", []):
        assert text in out, f"stdout lacks {text!r}{shown}"
    for text in expect.get("stderr_contains", []):
        assert text in err, f"stderr lacks {text!r}{shown}"
    for text in expect.get("stdout_excludes", []):
        assert text not in out, f"stdout has {text!r}{shown}"
    for text in expect.get("stderr_excludes", []):
        assert text not in err, f"stderr has {text!r}{shown}"
    if "stdout_starts_with" in expect:
        assert out.startswith(expect["stdout_starts_with"]), f"stdout prefix{shown}"
    for key, value in expect.get("stdout_json", {}).items():
        assert json.loads(out)[key] == value, f"stdout JSON {key!r}{shown}"
    for text, count in expect.get("stderr_counts", {}).items():
        assert err.count(text) == count, f"stderr has {text!r} x{err.count(text)}{shown}"
    if "requests" in expect:
        assert len(api.requests) == expect["requests"], f"request count{shown}"

    want = expect.get("request")
    if want:
        assert api.requests, f"no request was made{shown}"
        request = api.requests[-1]
        if "url" in want:
            assert str(request.url) == want["url"]
        for header, value in want.get("headers", {}).items():
            assert request.headers.get(header) == value, header
        for key, value in want.get("body", {}).items():
            assert api.sent.get(key) == value, f"body[{key!r}] = {api.sent.get(key)!r}"
        if "body_keys" in want:
            assert sorted(api.sent) == want["body_keys"]
