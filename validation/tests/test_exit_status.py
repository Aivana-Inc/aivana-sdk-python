"""The suite's exit status is what a script or a release gate sees, so it is tested like any other behaviour.

Each case runs a small throwaway project (this suite's own conftest.py and pytest.ini, plus one or two tiny tests)
in a subprocess and checks the status. Nothing here touches the network or the SDK under test.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def run_project(tmp_path, body, *, env=None, args=()):
    proj = tmp_path / "proj"
    (proj / "tests").mkdir(parents=True)
    shutil.copy(HERE / "conftest.py", proj / "conftest.py")
    shutil.copy(HERE / "pytest.ini", proj / "pytest.ini")
    (proj / "tests" / "test_sample.py").write_text("import pytest\n" + textwrap.dedent(body))
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("AIVANA_")}
    full_env["AIVANA_RESULTS_DIR"] = str(tmp_path / "results")
    full_env.update(env or {})
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", *args], cwd=proj, env=full_env,
                       capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def test_a_case_that_fails_is_exit_1(tmp_path):
    code, out = run_project(tmp_path, '''
        @pytest.mark.case("T-01", "Area", "fails")
        def test_fails():
            assert False
    ''')
    assert code == 1, out


def test_a_failing_test_with_no_matrix_row_is_still_exit_1(tmp_path):
    code, out = run_project(tmp_path, '''
        def test_fails_outside_the_matrix():
            assert False
    ''')
    assert code == 1, out


def test_a_setup_error_is_exit_1(tmp_path):
    code, out = run_project(tmp_path, '''
        @pytest.fixture
        def broken():
            raise RuntimeError("setup blew up")

        @pytest.mark.case("T-02", "Area", "setup error")
        def test_uses_broken(broken):
            pass
    ''')
    assert code == 1, out


def test_a_known_defect_that_still_fails_is_exit_0(tmp_path):
    code, out = run_project(tmp_path, '''
        @pytest.mark.case("T-03", "Area", "known defect")
        @pytest.mark.xfail(reason="F9: documented defect")
        def test_known():
            assert False
    ''')
    assert code == 0, out


def test_a_known_defect_that_now_passes_is_exit_0_with_a_notice(tmp_path):
    code, out = run_project(tmp_path, '''
        @pytest.mark.case("T-04", "Area", "fixed since")
        @pytest.mark.xfail(reason="F9: documented defect")
        def test_now_passes():
            assert True
    ''')
    assert code == 0, out
    assert "NOTICE  T-04 now passes" in out


def test_strict_known_keeps_pytests_own_failure_for_a_fixed_defect(tmp_path):
    code, out = run_project(tmp_path, '''
        @pytest.mark.case("T-04", "Area", "fixed since")
        @pytest.mark.xfail(reason="F9: documented defect")
        def test_now_passes():
            assert True
    ''', env={"AIVANA_STRICT_KNOWN": "1"})
    assert code == 1, out


def test_a_fixed_defect_does_not_hide_a_real_failure_beside_it(tmp_path):
    code, out = run_project(tmp_path, '''
        @pytest.mark.case("T-04", "Area", "fixed since")
        @pytest.mark.xfail(reason="F9: documented defect")
        def test_now_passes():
            assert True

        @pytest.mark.case("T-05", "Area", "really fails")
        def test_really_fails():
            assert False
    ''')
    assert code == 1, out


def test_nothing_collected_is_not_a_pass(tmp_path):
    code, out = run_project(tmp_path, '''
        def test_one():
            pass
    ''', args=("-k", "no_such_case_anywhere"))
    assert code == 5, out


def test_the_script_no_longer_swallows_pytests_status():
    script = (HERE / "run_validation.sh").read_text()
    pytest_lines = [l for l in script.splitlines() if "python -m pytest" in l and not l.lstrip().startswith("#")]
    assert len(pytest_lines) == 1
    assert "|| true" not in pytest_lines[0], "pytest's status is being thrown away again"
    assert re.search(r'^\s*exit "\$status"\s*$', script, re.M), "the script must exit with pytest's status"
