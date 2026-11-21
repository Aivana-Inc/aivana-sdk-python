"""The versions in requirements.txt are the versions that were tested together. If they drift, say so."""

import importlib.metadata
import re
from pathlib import Path

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"


def pins() -> dict[str, str]:
    found = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([0-9][^\s#]*)", line.strip())
        if match:
            found[match.group(1).lower()] = match.group(2)
    return found


def test_every_dependency_is_pinned_to_one_exact_version():
    pinned = pins()
    assert {"aivana", "fastapi", "starlette", "uvicorn", "python-dotenv"} <= set(pinned), pinned
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        assert not line or "==" in line, f"not an exact pin: {line}"


def test_the_installed_packages_are_the_pinned_ones():
    for name, version in pins().items():
        assert importlib.metadata.version(name) == version, f"{name}: requirements.txt says {version}"


def test_the_documented_python_floor_is_the_one_the_code_enforces():
    from basic_chat import __main__ as cli

    floor = f"{cli.MIN_PYTHON[0]}.{cli.MIN_PYTHON[1]}"
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    assert f"Python {floor} or newer" in readme
    assert "Python 3.10 or newer" not in readme and "Requires Python 3.10" not in readme
    workflow = (Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    block = workflow[workflow.index("  starter:"):workflow.index("  # One fixed check name")]
    assert f'python-version: ["{floor}"' in block, "CI must test the lowest Python the starter claims"
