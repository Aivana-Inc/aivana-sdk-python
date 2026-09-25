"""The `aivana` command: behaviour that depends on the platform, not the contract.

The contract itself (arguments, requests, messages, exit codes) is the shared
conformance suite in conformance/cli.json, run by test_conformance.py here and by
the Node CLI's own runner. What stays in this file cannot be expressed in that
suite: real pipes and terminals, signals, and a reader that closes early.

    python3 -m pytest tests/ -q
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cli_doubles import Stdin, Terminal

from aivana import cli

REPO = Path(__file__).resolve().parent.parent

STAGES = [["stage", {"loading": s, "stage": s}] for s in (
    "Selecting the right intelligence",
    "Reviewing multiple perspectives",
    "Resolving disagreements",
    "Preparing the synthesized answer",
)]
ANSWER = {"status": 200, "events": STAGES + [
    ["delta", {"text": "Hello"}], ["delta", {"text": " world."}],
    ["done", {"finish_reason": "stop", "usage": {}}]]}


@pytest.fixture
def pipe(monkeypatch):
    """stdin as a real OS pipe; the test gets the write end."""
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, "r")
    monkeypatch.setattr(sys, "stdin", reader)
    yield write_fd
    reader.close()
    try:
        os.close(write_fd)
    except OSError:
        pass                                    # the test already closed it


def test_progress_draws_on_a_terminal_and_is_wiped_before_the_answer(
        api, run, monkeypatch):
    api.response = ANSWER
    terminal = Terminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    code, out, _ = run("hi")
    drawn = terminal.getvalue()
    assert code == cli.EXIT_OK and out == "Hello world.\n"
    assert "\rSelecting the right intelligence…" in drawn
    assert "\rPreparing the synthesized answer…" in drawn
    assert drawn.endswith("\r"), "the status line must be cleared, not left behind"


def test_input_from_a_real_pipe_is_read(api, run, pipe):
    api.response = ANSWER
    os.write(pipe, b"ERROR: deadlock detected\n")
    os.close(pipe)
    run("What's causing this?")
    assert api.sent["prompt"] == "ERROR: deadlock detected\n\nWhat's causing this?"


@pytest.mark.skipif(os.name == "nt", reason="select() cannot watch a pipe on Windows")
def test_a_pipe_nobody_writes_to_cannot_hang_the_command(api, run, monkeypatch, pipe):
    """An agent's shell, `ssh host aivana ...`, a subprocess that inherited its
    parent's stdin: open, never written, never closed. Found the hard way: the
    first end-to-end run of this CLI hung on exactly this."""
    api.response = ANSWER
    monkeypatch.setattr(cli, "STDIN_WAIT_S", 0.2)
    code, _, err = run("Just the question")
    assert code == cli.EXIT_OK
    assert api.sent["prompt"] == "Just the question"
    assert "no piped input arrived within 0.2s" in err
    assert "< /dev/null" in err


def test_binary_piped_input_is_refused(api, run, monkeypatch):
    class BinaryStdin(Stdin):
        def read(self, *_):
            raise UnicodeDecodeError("utf-8", b"\x89", 0, 1, "invalid start byte")

    monkeypatch.setattr(sys, "stdin", BinaryStdin(tty=False))
    code, _, err = run("What is this?")
    assert code == cli.EXIT_USAGE
    assert "isn't text" in err
    assert not api.requests


def test_ctrl_c_exits_130(api, monkeypatch):
    def interrupted(request):
        raise KeyboardInterrupt

    monkeypatch.setattr(api, "handle", interrupted)
    assert cli.main(["hi"]) == cli.EXIT_INTERRUPTED


def test_a_reader_closing_the_pipe_ends_quietly(api, monkeypatch):
    """`aivana ... | head -3`: the reader leaving early is not a crash."""
    class ClosedPipe(io.StringIO):
        def write(self, _):
            raise BrokenPipeError

    api.response = ANSWER
    monkeypatch.setattr(sys, "stdout", ClosedPipe())
    assert cli.main(["hi"]) == cli.EXIT_FAILED


def test_python_dash_m_runs_the_same_program():
    result = subprocess.run([sys.executable, "-m", "aivana", "--version"], cwd=REPO,
                            stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("aivana ")
