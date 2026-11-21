"""The smoke test holds a production API key, and the publish workflow is gated on it. YAML cannot be unit tested, so
these read the workflow files and the shared composite action as text and pin the properties that keep the key safe
and the gate real. If one fails, read the comments at the top of .github/workflows/smoke.yml and
.github/actions/production-smoke/action.yml before changing the test."""
from __future__ import annotations

import re
from pathlib import Path

GITHUB = Path(__file__).resolve().parent.parent / ".github"


def _code(path):
    """The file without its comment lines: the comments say things like "no id-token permission"."""
    text = (GITHUB / path).read_text(encoding="utf-8")
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))


SMOKE_YML = _code("workflows/smoke.yml")
PUBLISH_YML = _code("workflows/publish.yml")
ACTION = _code("actions/production-smoke/action.yml")


def _job(text, name):
    """The text of one top-level job, from its name to the next job (or the end of the file)."""
    start = text.find(f"\n  {name}:\n")
    assert start >= 0, f"no job named {name}"
    rest = text[start + 1:]
    nxt = re.search(r"\n  [a-z][a-z0-9-]*:\n", rest[1:])
    return rest if nxt is None else rest[: nxt.start() + 2]


SMOKE_JOBS = {"smoke.yml": _job(SMOKE_YML, "smoke"), "publish.yml": _job(PUBLISH_YML, "smoke")}
PUBLISH_JOB = _job(PUBLISH_YML, "publish")


def _secrets(text):
    return set(re.findall(r"secrets\.([A-Z_]+)", text))


def test_the_manual_workflow_can_only_be_started_by_hand():
    on = re.search(r"^on:\n((?:[ ]+.*\n)+)", SMOKE_YML, re.M).group(1)
    assert [l.strip().rstrip(":") for l in on.splitlines() if l.strip()] == ["workflow_dispatch"]
    assert not re.search(r"pull_request|push:|schedule:|workflow_call", SMOKE_YML.split("jobs:")[0])


def test_the_release_gate_is_a_job_of_publish_yml_not_a_reusable_workflow():
    """A called workflow got the key empty in the first release run (Node v0.8.0)."""
    assert not re.search(r"uses:\s*\./\.github/workflows/", PUBLISH_YML), "publish.yml calls a reusable workflow again"
    assert "workflow_call" not in SMOKE_YML, "smoke.yml became a reusable workflow again"
    assert "secrets: inherit" not in PUBLISH_YML, "the gate must not be handed every repository secret"


def test_each_job_declares_the_protected_environment_and_reads_the_key_from_it():
    for file, body in SMOKE_JOBS.items():
        assert "\n    environment: production-smoke\n" in body, file
        assert "api-key: ${{ secrets.AIVANA_API_KEY }}" in body, file
        assert _secrets(body) == {"AIVANA_API_KEY"}, file


def test_each_job_can_read_the_repository_and_nothing_else_with_a_time_limit():
    for file, body in SMOKE_JOBS.items():
        assert "id-token" not in body, file
        assert not re.search(r": write\b", body), file
        assert re.search(r"timeout-minutes: \d+", body), file


def test_smoke_yml_has_read_only_permissions_and_one_run_at_a_time_never_cancelled():
    assert "permissions:\n  contents: read" in SMOKE_YML
    assert "id-token" not in SMOKE_YML and not re.search(r": write\b", SMOKE_YML)
    assert "concurrency:\n  group: production-smoke\n  cancel-in-progress: false" in SMOKE_YML


def test_the_gate_in_publish_yml_has_the_same_permissions_and_lock_set_on_the_job():
    body = SMOKE_JOBS["publish.yml"]
    assert "permissions:\n      contents: read" in body
    assert "concurrency:\n      group: production-smoke\n      cancel-in-progress: false" in body


def test_the_key_is_the_only_secret_in_the_smoke_workflow_or_the_gates_job():
    assert _secrets(SMOKE_YML + SMOKE_JOBS["publish.yml"]) == {"AIVANA_API_KEY"}


def test_the_composite_action_never_reads_the_secrets_context_the_key_arrives_as_an_input():
    assert "secrets." not in ACTION
    assert "inputs:\n  api-key:" in ACTION


def test_the_key_reaches_only_the_two_steps_that_run_the_script_never_the_build_steps():
    steps = ACTION.split("\n    - name: ")[1:]
    with_key = [s.splitlines()[0] for s in steps if "inputs.api-key" in s]
    assert with_key == ["Check the setup (no calls)", "Run the smoke test against production"]


def test_it_tests_the_built_wheel_in_a_fresh_environment_with_the_version_it_expects():
    assert "python -m build --wheel" in ACTION
    assert "python -m venv" in ACTION
    assert "EXPECTED_SDK_VERSION=" in ACTION
    assert ACTION.count("working-directory: ${{ env.SMOKE_DIR }}") == 2
    # both steps that run the script use the venv's interpreter, not the runner's
    commands = re.findall(r"^      run: (.*smoke\.py.*)$", ACTION, re.M)
    assert commands == ["${{ env.SMOKE_PY }} smoke.py --dry-run", "${{ env.SMOKE_PY }} smoke.py"]


def test_both_jobs_use_the_shared_action_so_the_manual_run_and_the_gate_cannot_drift_apart():
    for body in SMOKE_JOBS.values():
        assert "uses: ./.github/actions/production-smoke\n" in body


def test_every_run_step_of_the_action_names_a_shell_and_the_action_is_composite():
    """GitHub refuses a composite action at run time if a run step has no shell."""
    assert "\nruns:\n  using: composite\n" in ACTION
    run_steps = [s for s in ACTION.split("\n    - name: ")[1:] if "\n      run:" in s]
    assert len(run_steps) >= 3
    for st in run_steps:
        assert "\n      shell: bash\n" in st, f"step without a shell: {st.splitlines()[0]}"


def test_publishing_waits_for_the_smoke_test():
    assert "\n  publish:\n    needs: smoke\n" in PUBLISH_YML


def test_the_publish_job_is_still_the_only_one_that_can_publish():
    assert PUBLISH_YML.count("id-token: write") == 1
    assert "id-token: write" in PUBLISH_JOB
    assert "id-token" not in SMOKE_JOBS["publish.yml"]


def test_the_gate_cannot_be_skipped_by_a_condition():
    assert not re.search(r"\bif:", SMOKE_JOBS["publish.yml"])
    assert "continue-on-error" not in PUBLISH_YML
