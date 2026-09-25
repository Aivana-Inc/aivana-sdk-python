"""Fixtures for the CLI suites (test_cli.py, test_conformance.py)."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cli_doubles import FakeAPI, Stdin  # noqa: E402

from aivana import cli  # noqa: E402
from aivana import client as sdk  # noqa: E402

TEST_KEY = "ai_live_conformance_not_real"


@pytest.fixture
def api(monkeypatch):
    """A FakeAPI behind the real SDK, a key in the environment, a terminal on stdin."""
    fake = FakeAPI()
    real = httpx.Client
    monkeypatch.setattr(sdk.httpx, "Client",
                        lambda **kw: real(transport=httpx.MockTransport(fake.handle), **kw))
    # The CLI writes the key and base into the SDK's module-level config; these
    # restore both afterwards so no other test inherits them.
    monkeypatch.setattr(sdk, "api_key", None)
    monkeypatch.setattr(sdk, "api_base", sdk.api_base)
    monkeypatch.setenv("AIVANA_API_KEY", TEST_KEY)
    monkeypatch.delenv("AIVANA_API_BASE", raising=False)
    monkeypatch.setattr(sys, "stdin", Stdin(tty=True))
    return fake


@pytest.fixture
def run(capsys):
    """Run `aivana ARGV...` in-process: returns (exit code, stdout, stderr)."""
    def _run(*argv: str) -> tuple[int, str, str]:
        code = cli.main(list(argv))
        out, err = capsys.readouterr()
        return code, out, err
    return _run
