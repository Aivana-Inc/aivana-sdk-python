"""The commands a person runs: setup, doctor, start, verify-live."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from basic_chat import __main__ as cli

from .conftest import EXPORTED_BLUEPRINT
from .support import KEY, Upstream, answer, serve

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A copy of the folder's .env.example, so setup can be tried without touching the real one."""
    (tmp_path / ".env.example").write_bytes((ROOT / ".env.example").read_bytes())
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    return tmp_path


def test_setup_creates_a_private_env_file_and_never_overwrites_one(workdir, capsys):
    assert cli.main(["setup"]) == 0
    env = workdir / ".env"
    assert env.read_text() == (ROOT / ".env.example").read_text()
    if sys.platform != "win32":
        assert env.stat().st_mode & 0o777 == 0o600, "a file that will hold a key is private to its owner"
    env.write_text("AIVANA_API_KEY=my_real_key\n")
    assert cli.main(["setup"]) == 0
    assert env.read_text() == "AIVANA_API_KEY=my_real_key\n", "an existing .env is left exactly as it is"
    assert "Kept your existing .env" in capsys.readouterr().out


def test_env_file_values_never_replace_the_real_environment(workdir, monkeypatch):
    (workdir / ".env").write_text('AIVANA_API_KEY=from_the_file\nPORT="4321"\nAIVANA_BLUEPRINT_NAME=Juniper Assistant\n')
    for name in ("AIVANA_API_KEY", "PORT", "AIVANA_BLUEPRINT_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AIVANA_API_KEY", "from_the_shell")
    cli._load_env_file()
    assert os.environ["AIVANA_API_KEY"] == "from_the_shell", "the shell wins, as with `uvicorn --env-file` and Node's --env-file"
    assert os.environ["PORT"] == "4321" and os.environ["AIVANA_BLUEPRINT_NAME"] == "Juniper Assistant"
    monkeypatch.delenv("PORT"), monkeypatch.delenv("AIVANA_BLUEPRINT_NAME")


def test_doctor_reports_readiness_without_calling_the_api(workdir, monkeypatch, capsys):
    monkeypatch.setenv("AIVANA_API_KEY", KEY)
    monkeypatch.delenv("AIVANA_BLUEPRINT_FILE", raising=False)
    monkeypatch.delenv("AIVANA_BLUEPRINT_NAME", raising=False)
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "No API request was made" in out and KEY not in out and "default chat settings" in out


@pytest.mark.parametrize("key", ["", "YOUR_ACTIVE_KEY", "ai_live_xxx"])
def test_doctor_names_the_problem_without_printing_a_value(workdir, monkeypatch, capsys, key):
    monkeypatch.setenv("AIVANA_API_KEY", key)
    assert cli.main(["doctor"]) == 1
    err = capsys.readouterr().err
    assert "AIVANA_API_KEY" in err and (not key or key not in err)


def test_doctor_checks_the_blueprint_and_its_name(workdir, monkeypatch, capsys):
    path = workdir / "business definition.json"
    path.write_text(json.dumps(EXPORTED_BLUEPRINT))
    monkeypatch.setenv("AIVANA_API_KEY", KEY)
    monkeypatch.setenv("AIVANA_BLUEPRINT_FILE", str(path))
    monkeypatch.setenv("AIVANA_BLUEPRINT_NAME", "Juniper Assistant")
    assert cli.main(["doctor"]) == 0
    assert 'Blueprint name: "Juniper Assistant"' in capsys.readouterr().out
    path.write_text('{"private_secret":')
    assert cli.main(["doctor"]) == 1
    assert "private_secret" not in capsys.readouterr().err


def test_a_name_with_no_blueprint_is_noted_and_ignored(workdir, monkeypatch, capsys):
    monkeypatch.setenv("AIVANA_API_KEY", KEY)
    monkeypatch.delenv("AIVANA_BLUEPRINT_FILE", raising=False)
    monkeypatch.setenv("AIVANA_BLUEPRINT_NAME", "Orphan")
    assert cli.main(["doctor"]) == 0
    assert "ignored" in capsys.readouterr().out


def test_verify_live_is_billed_so_it_refuses_to_run_without_being_told(monkeypatch, capsys):
    monkeypatch.setenv("AIVANA_API_KEY", KEY)
    assert cli.main(["verify-live"]) == 2
    assert "billed" in capsys.readouterr().err


def test_unknown_commands_print_usage(capsys):
    assert cli.main(["frobnicate"]) == 2 and "Usage" in capsys.readouterr().err


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_the_real_command_starts_serves_a_chat_and_prints_no_secret(tmp_path):
    """`python -m basic_chat` in a fresh process, configured only through the environment, talking to a stand-in API."""
    async def respond(entry, request, count):
        return answer()

    upstream = Upstream(respond)
    with serve(upstream.app) as api:
        port = free_port()
        blueprint = tmp_path / "business definition.json"
        blueprint.write_text(json.dumps(EXPORTED_BLUEPRINT))
        env = {**os.environ, "AIVANA_API_KEY": KEY, "AIVANA_API_BASE": api, "PORT": str(port),
               "AIVANA_BLUEPRINT_FILE": str(blueprint), "AIVANA_BLUEPRINT_NAME": "Juniper Assistant"}
        child = subprocess.Popen([sys.executable, "-m", "basic_chat"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(200):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    if child.poll() is not None:
                        pytest.fail(f"the command exited: {child.stderr.read()}")
                    time.sleep(0.05)
            import httpx

            origin = f"http://127.0.0.1:{port}"
            reply = httpx.post(f"{origin}/api/chat", headers={"Origin": origin}, json={"message": "hello"}, timeout=10)
            assert reply.status_code == 200
            assert upstream.seen[0]["headers"]["x-api-key"] == KEY
            assert upstream.seen[0]["body"]["system"] == "Be clear" and upstream.seen[0]["body"]["max_tokens"] == 2048
            assert httpx.get(f"{origin}/api/config", timeout=5).json()["blueprint"]["name"] == "Juniper Assistant"
            assert "server" not in {name.lower() for name in httpx.get(f"{origin}/api/config").headers}, "the server does not announce itself"
        finally:
            child.terminate()
            out, err = child.communicate(timeout=15)
        assert "Exported blueprint loaded locally" in out and "ignored" not in out
        assert KEY not in out and KEY not in err
        assert "Traceback" not in err, err


def test_a_busy_port_is_reported_in_plain_words(tmp_path):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        env = {**os.environ, "AIVANA_API_KEY": KEY, "PORT": str(port), "AIVANA_BLUEPRINT_FILE": ""}
        done = subprocess.run([sys.executable, "-m", "basic_chat"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
    assert done.returncode == 1
    assert "could not start" in done.stderr and "Traceback" not in done.stderr, done.stderr


def _verify_live(monkeypatch, api_base: str):
    monkeypatch.setenv("AIVANA_API_KEY", KEY)
    monkeypatch.setenv("AIVANA_API_BASE", api_base)
    monkeypatch.delenv("AIVANA_BLUEPRINT_FILE", raising=False)
    return cli.main(["verify-live", "--billable"])


def test_verify_live_passes_when_the_follow_up_recalls_the_first_turn(monkeypatch, capsys):
    """The billed check, run against the stand-in API: two turns through the real app, no credit spent."""
    async def respond(entry, request, count):
        return answer(answer="Noted: Juniper." if count == 1 else "You called the project Juniper.")

    upstream = Upstream(respond)
    with serve(upstream.app) as api:
        assert _verify_live(monkeypatch, api) == 0
    out, err = capsys.readouterr()
    assert "Live turn 1: passed" in out and "follow-up context confirmed" in out and "Two-turn live app check passed" in out
    assert KEY not in out + err and "Juniper." not in out and "You called" not in out, "no conversation content or credentials printed"
    second = upstream.seen[1]["body"]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"] and second[1]["content"] == "Noted: Juniper."


def test_verify_live_fails_with_a_fixed_code_when_the_follow_up_forgets(monkeypatch, capsys):
    async def respond(entry, request, count):
        return answer(answer="Noted." if count == 1 else "I have no idea.")

    with serve(Upstream(respond).app) as api:
        assert _verify_live(monkeypatch, api) == 1
    out, err = capsys.readouterr()
    assert "follow_up_context_not_demonstrated" in err and "I have no idea" not in out + err and KEY not in out + err


def test_verify_live_reports_a_fixed_code_for_an_api_error_and_never_its_text(monkeypatch, capsys):
    from starlette.responses import JSONResponse

    async def respond(entry, request, count):
        return JSONResponse({"error": {"code": "insufficient_credit", "message": KEY}}, status_code=402)

    with serve(Upstream(respond).app) as api:
        assert _verify_live(monkeypatch, api) == 1
    out, err = capsys.readouterr()
    assert "insufficient_credit" in err and KEY not in out + err


def test_ctrl_c_during_an_answer_stops_the_server_promptly_and_cancels_the_call(tmp_path):
    """Shutting down with a request in flight must not hang, and must not leave the call to Aivana running."""
    import signal

    import httpx

    from .support import sse

    holder: dict = {}

    async def respond(entry, request, count):
        return sse(("delta", {"text": "start"}), (30, "delta", {"text": "never"}), upstream=holder["upstream"])

    upstream = Upstream(respond)
    holder["upstream"] = upstream
    with serve(upstream.app) as api:
        port = free_port()
        env = {**os.environ, "AIVANA_API_KEY": KEY, "AIVANA_API_BASE": api, "PORT": str(port), "AIVANA_BLUEPRINT_FILE": ""}
        child = subprocess.Popen([sys.executable, "-m", "basic_chat"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(200):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    time.sleep(0.05)
            origin = f"http://127.0.0.1:{port}"
            stream = httpx.Client(timeout=30).stream("POST", f"{origin}/api/chat/stream", headers={"Origin": origin}, json={"message": "hi"})
            response = stream.__enter__()
            assert next(response.iter_lines()), "the first piece arrived; an answer is in flight"
            started = time.monotonic()
            child.send_signal(signal.SIGINT if sys.platform != "win32" else signal.CTRL_C_EVENT)
            code = child.wait(timeout=10)
            assert time.monotonic() - started < 6, "shutdown must not wait out a long answer"
            assert code == 0, "Ctrl+C is a normal way to stop, not a failure"
            assert upstream.closed.wait(2), "the call to Aivana was still open after the server stopped"
        finally:
            if child.poll() is None:
                child.kill()
            _, err = child.communicate(timeout=10)
        assert "Traceback" not in err, err


def test_an_older_python_is_told_plainly_before_anything_is_imported(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "version_info", (3, 10, 14, "final", 0))
    for command in ([], ["doctor"], ["setup"], ["verify-live", "--billable"]):
        assert cli.main(command) == 1
        assert "needs Python 3.11 or newer" in capsys.readouterr().err
