"""Commands: `python -m basic_chat [start | setup | doctor | verify-live --billable]`. No command means start."""

from __future__ import annotations

import asyncio
import importlib
import os
import re
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_PYTHON = (3, 11)  # FastAPI and Starlette's current versions need it (the SDK itself supports 3.10)


def _load_env_file() -> None:
    """Load ROOT/.env without replacing anything already set in the real environment (the same rule as
    `uvicorn --env-file` and Node's `--env-file`)."""
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)


def _start() -> int:
    import uvicorn

    from .app import create_app
    from .blueprint import load_blueprint
    from .client import SdkClient
    from .config import read_configuration

    settings = read_configuration()
    blueprint = load_blueprint()
    app = create_app(
        client=SdkClient(settings.api_key, settings.api_base),
        blueprint=blueprint,
        blueprint_name=settings.blueprint_name,
    )
    if settings.blueprint_name and not blueprint:
        print("AIVANA_BLUEPRINT_NAME is set but no Blueprint is loaded, so it is ignored.", flush=True)
    print(
        "Exported blueprint loaded locally. Restart and reload after replacing the file."
        if blueprint
        else "Using the default chat settings. Add blueprint-definition.json to use an Agent Kit export."
    )
    try:
        sock = _listen(settings.port)
    except OSError:
        print("The local chat server could not start. Check PORT or whether another app is using it.", file=sys.stderr)
        return 1
    print(
        f"Basic AI Chat: http://127.0.0.1:{settings.port}\n"
        "API key stays on this server. Messages use Aivana account credit. Press Ctrl+C to stop.",
        flush=True,
    )
    config = uvicorn.Config(app, host="127.0.0.1", port=settings.port, log_level="warning", access_log=False,
                            server_header=False, timeout_graceful_shutdown=2)
    try:
        uvicorn.Server(config).run(sockets=[sock])
    except KeyboardInterrupt:
        pass  # Ctrl+C is how this is stopped: uvicorn has already shut down cleanly, so there is nothing to report
    return 0


def _listen(port: int) -> socket.socket:
    """Open the port ourselves, on 127.0.0.1 only: this starter is never reachable from another computer.

    Doing it here (rather than letting uvicorn do it) means a busy port is an error we can explain, not
    a log line and an exit code from inside uvicorn.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform != "win32":  # on Windows this option would let two programs share the port
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.set_inheritable(True)
    except OSError:
        sock.close()
        raise
    return sock


def _setup() -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"Install Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer, then run setup again.", file=sys.stderr)
        return 1
    target = ROOT / ".env"
    try:
        # "x" never overwrites: an existing .env (with a real key in it) is left exactly as it is.
        with open(ROOT / ".env.example", "rb") as source, open(target, "xb") as out:
            shutil.copyfileobj(source, out)
        os.chmod(target, 0o600)
        print("Created .env. Add your own AIVANA_API_KEY in your editor.")
    except FileExistsError:
        print("Kept your existing .env unchanged.")
    print("Next: pip install -r requirements.txt, edit .env, python -m basic_chat doctor, then python -m basic_chat.")
    return 0


def _doctor() -> int:
    from .blueprint import BlueprintError, load_blueprint
    from .config import ConfigError, read_configuration

    try:
        for module in ("aivana", "fastapi", "uvicorn", "dotenv"):
            importlib.import_module(module)  # presence check only
        from . import app  # noqa: F401

        settings = read_configuration()
        blueprint = load_blueprint()
        print(
            "Blueprint definition is valid and supported. Loaded locally; no saved-agent service is used."
            if blueprint
            else "Using default chat settings. No blueprint definition file was found."
        )
        if settings.blueprint_name:
            print(
                f'Blueprint name: "{settings.blueprint_name}" (from AIVANA_BLUEPRINT_NAME).'
                if blueprint
                else "AIVANA_BLUEPRINT_NAME is set but no Blueprint is loaded, so it will be ignored."
            )
        print(f"Local configuration and dependencies are ready. Start with python -m basic_chat, then open http://127.0.0.1:{settings.port}.")
        print("No API request was made. Key validity, account credit and port availability are checked when used.")
        print("After starting, send a test message, check live streaming, and ask a follow-up. These requests use account credit.")
        return 0
    except (BlueprintError, ConfigError) as error:
        print(error, file=sys.stderr)
    except ImportError:
        print("Not ready. Run pip install -r requirements.txt inside your virtual environment.", file=sys.stderr)
    return 1


async def _verify_live() -> int:
    """Two billed turns through the real app on a real local port. Only ever run on purpose."""
    import httpx
    import uvicorn

    from .app import create_app
    from .client import SdkClient
    from .config import read_configuration

    settings = read_configuration()
    app = create_app(client=SdkClient(settings.api_key, settings.api_base))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", access_log=False))
    serving = asyncio.ensure_future(server.serve())
    try:
        while not server.started:
            if serving.done():
                raise RuntimeError("setup")
            await asyncio.sleep(0.05)
        origin = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
        history: list[dict] = []
        context: dict = {}
        async with httpx.AsyncClient(timeout=125) as http:
            for message in (
                "The project nickname for this conversation is Juniper. Acknowledge in one short sentence.",
                "What project nickname did I give you? Reply briefly.",
            ):
                response = await http.post(
                    f"{origin}/api/chat", headers={"Origin": origin},
                    json={"message": message, "history": history, "context": context},
                )
                result = response.json()
                if response.status_code != 200:
                    raise RuntimeError(result.get("error", {}).get("code", "request_failed"))
                if not result.get("answer", "").strip():
                    raise RuntimeError("empty_answer")
                if history and not re.search(r"\bJuniper\b", result["answer"], re.IGNORECASE):
                    raise RuntimeError("follow_up_context_not_demonstrated")
                history += [{"role": "user", "content": message}, {"role": "assistant", "content": result["answer"]}]
                context = result["context"]
                print(f"Live turn {len(history) // 2}: passed" + (" (follow-up context confirmed)." if len(history) > 2 else " (nonempty answer)."))
        print("Two-turn live app check passed. No conversation content or credentials printed.")
        return 0
    except Exception as error:  # noqa: BLE001 - only fixed public codes are ever shown, never SDK text or credentials
        code = str(error) if re.fullmatch(r"[a-z_]+", str(error)) else "connection_or_setup_error"
        print(f"Live check failed: {code}. A request Aivana may have accepted was not sent again.", file=sys.stderr)
        return 1
    finally:
        server.should_exit = True
        await asyncio.gather(serving, return_exceptions=True)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"This starter needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer. Install it, make a new virtual environment, and try again.", file=sys.stderr)
        return 1
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "start"
    if command == "setup":
        return _setup()
    if command not in ("start", "doctor", "verify-live"):
        print("Usage: python -m basic_chat [start | setup | doctor | verify-live --billable]", file=sys.stderr)
        return 2
    try:
        _load_env_file()
    except ImportError:
        print("Not ready. Run pip install -r requirements.txt inside your virtual environment.", file=sys.stderr)
        return 1
    if command == "doctor":
        return _doctor()
    if command == "verify-live":
        if "--billable" not in args:
            print("verify-live makes two billed requests. Run it again with --billable to confirm.", file=sys.stderr)
            return 2
        from .config import ConfigError

        try:
            return asyncio.run(_verify_live())
        except ConfigError as error:
            print(error, file=sys.stderr)
            return 1
    from .blueprint import BlueprintError
    from .config import ConfigError

    try:
        return _start()
    except (BlueprintError, ConfigError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
