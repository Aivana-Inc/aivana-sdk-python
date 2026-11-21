"""The smoke workflow holds a production API key, and the publish workflow is gated on it. YAML cannot be unit tested,
so these read the two files as text and pin the properties that keep the key safe and the gate real.
If one fails, read the comment at the top of .github/workflows/smoke.yml before changing the test."""
from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _code(name):
    """The file without its comment lines: the comments say things like "no id-token permission"."""
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))


SMOKE = _code("smoke.yml")
PUBLISH = _code("publish.yml")


def test_the_smoke_workflow_can_only_be_started_by_hand_or_by_the_publish_gate():
    on = re.search(r"^on:\n((?:[ ]+.*\n)+)", SMOKE, re.M).group(1)
    triggers = sorted(l.strip().rstrip(":") for l in on.splitlines() if l.strip())
    assert triggers == ["workflow_call", "workflow_dispatch"]
    assert not re.search(r"pull_request|push:|schedule:", SMOKE.split("jobs:")[0])


def test_the_key_lives_in_a_protected_environment_and_is_the_only_secret_used():
    assert "environment: production-smoke" in SMOKE
    assert "secrets.AIVANA_API_KEY" in SMOKE
    assert set(re.findall(r"secrets\.([A-Z_]+)", SMOKE)) == {"AIVANA_API_KEY"}


def test_the_key_reaches_only_the_two_steps_that_run_the_script():
    steps = SMOKE.split("\n      - name: ")[1:]
    with_key = [s.splitlines()[0] for s in steps if "secrets.AIVANA_API_KEY" in s]
    assert with_key == ["Check the setup (no calls)", "Run the smoke test against production"]


def test_the_job_can_read_the_repository_and_nothing_else():
    assert "id-token" not in SMOKE
    assert not re.search(r": write\b", SMOKE)
    assert "permissions:\n  contents: read" in SMOKE


def test_only_one_run_at_a_time_and_a_run_in_progress_is_never_cancelled():
    assert "concurrency:\n  group: production-smoke\n  cancel-in-progress: false" in SMOKE


def test_it_tests_the_built_wheel_in_a_fresh_environment_with_the_version_it_expects():
    assert "python -m build --wheel" in SMOKE
    assert "python -m venv" in SMOKE
    assert "EXPECTED_SDK_VERSION=" in SMOKE
    assert "working-directory: ${{ env.SMOKE_DIR }}" in SMOKE
    # both steps that run the script use the venv's interpreter, not the runner's
    commands = re.findall(r"^        run: (.*smoke\.py.*)$", SMOKE, re.M)
    assert commands == ["${{ env.SMOKE_PY }} smoke.py --dry-run", "${{ env.SMOKE_PY }} smoke.py"]


def test_the_job_has_a_time_limit():
    assert re.search(r"timeout-minutes: \d+", SMOKE)


def test_publishing_waits_for_the_smoke_test_and_the_gate_is_passed_no_repository_secrets():
    assert "\n  smoke:\n    uses: ./.github/workflows/smoke.yml\n" in PUBLISH
    assert "\n  publish:\n    needs: smoke\n" in PUBLISH
    assert "secrets: inherit" not in PUBLISH


def test_the_publish_job_is_still_the_only_one_that_can_publish():
    assert PUBLISH.count("id-token: write") == 1
    assert "id-token" not in PUBLISH.split("\n  publish:\n")[0]


def test_the_gate_cannot_be_skipped_by_a_condition():
    smoke_job = PUBLISH.split("\n  publish:\n")[0].split("\n  smoke:\n")[1]
    assert not re.search(r"\bif:", smoke_job)
    assert "continue-on-error" not in PUBLISH
