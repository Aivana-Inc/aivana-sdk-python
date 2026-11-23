"""The standalone download: exactly the allowlisted files, nothing private, and it runs from a path with spaces."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from package_starter import FILES, package  # noqa: E402

from .support import KEY  # noqa: E402


def listing(folder: Path) -> set[str]:
    return {str(path.relative_to(folder)).replace("\\", "/") for path in folder.rglob("*") if path.is_file()}


def test_the_package_holds_exactly_the_allowlist_and_a_matching_manifest(tmp_path):
    out = package(tmp_path / "release with spaces")
    assert listing(out) == {*FILES, "LICENSE", "MANIFEST.json"}
    manifest = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["formatVersion"] == 1 and manifest["version"] == "1.0.0"
    assert set(manifest["sha256"]) == {*FILES, "LICENSE"}
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest, name


def test_the_package_never_includes_credentials_private_blueprints_tests_or_caches(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache"))
    (source / ".env").write_text(f"AIVANA_API_KEY={KEY}\n")
    (source / ".env.local").write_text(f"AIVANA_API_KEY={KEY}\n")
    (source / "blueprint-definition.json").write_text('{"private":"instructions"}')
    (source / "my-private-agent.json").write_text('{"private":"instructions"}')
    (source / "basic_chat" / "__pycache__").mkdir()
    (source / "basic_chat" / "__pycache__" / "app.cpython-313.pyc").write_bytes(b"x")
    out = package(tmp_path / "release", source=source)
    files = listing(out)
    for private in (".env", ".env.local", "blueprint-definition.json", "my-private-agent.json"):
        assert private not in files
    assert not any("__pycache__" in name or name.startswith(("tests/", "tools/")) for name in files)
    assert KEY not in "".join(path.read_text(errors="ignore") for path in out.rglob("*") if path.is_file() and path.suffix != ".avif")


def test_an_existing_output_folder_is_refused_so_a_release_is_never_mixed_with_leftovers(tmp_path):
    (tmp_path / "release").mkdir()
    (tmp_path / "release" / ".env").write_text("old")
    with pytest.raises(FileExistsError):
        package(tmp_path / "release")


def test_a_missing_file_or_a_link_stops_the_release(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache"))
    (source / "public" / "app.js").unlink()
    with pytest.raises(RuntimeError, match="regular files"):
        package(tmp_path / "one", source=source)
    if sys.platform != "win32":
        (source / "public" / "app.js").symlink_to(ROOT / "public" / "app.js")
        with pytest.raises(RuntimeError, match="regular files"):
            package(tmp_path / "two", source=source)


def test_the_extracted_package_runs_setup_and_doctor_from_a_path_with_spaces(tmp_path):
    out = package(tmp_path / "a folder with spaces")
    env = {k: v for k, v in os.environ.items() if not k.startswith("AIVANA_") and k != "PORT"}

    def run(*args, **extra):
        return subprocess.run([sys.executable, "-m", "basic_chat", *args], cwd=out, env={**env, **extra}, capture_output=True, text=True, timeout=60)

    first = run("setup")
    assert first.returncode == 0 and (out / ".env").is_file(), first.stderr
    (out / ".env").write_text(f"AIVANA_API_KEY={KEY}\nPORT=4567\n")
    again = run("setup")
    assert "Kept your existing .env" in again.stdout and KEY in (out / ".env").read_text(), "setup never overwrites a .env"
    doctor = run("doctor")
    assert doctor.returncode == 0, doctor.stderr
    assert "http://127.0.0.1:4567" in doctor.stdout and KEY not in doctor.stdout + doctor.stderr
    assert not (out / "blueprint-definition.json").exists()


def test_the_verification_tool_passes_on_a_freshly_built_package(tmp_path):
    """The same check the 'Basic Chat download' workflow runs on every operating system, here on this one."""
    out = package(tmp_path / "a folder with spaces")
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "verify_package.py"), str(out)], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Extracted download passed" in done.stdout and "No billed calls" in done.stdout
    assert KEY not in done.stdout + done.stderr
