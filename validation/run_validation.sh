#!/usr/bin/env bash
# Aivana Python SDK validation - one command.
#   bash run_validation.sh            # offline checks only (free, no key)
#   export AIVANA_API_KEY=ai_test_... && bash run_validation.sh    # + live checks on the dev host
#   (or put AIVANA_API_KEY=... in a .env file here; it is gitignored and loaded below)
# Optional: AIVANA_API_BASE=https://... to point live checks somewhere else.
# Test another version, or a release candidate that is not published yet:
#   AIVANA_SDK_SPEC=aivana==0.4.0  or  AIVANA_SDK_SPEC=/path/aivana-0.4.0-py3-none-any.whl   (default: the pin in requirements.txt)
#   AIVANA_EXPECT_SDK_VERSION=0.4.0   stop (exit 2) unless exactly that version is installed
#   AIVANA_RESULTS_DIR=/some/dir      write the matrix and evidence there, not into results/
#   AIVANA_STRICT_KNOWN=1             also fail when a known defect now passes
# Exit code: 0 nothing unexpected (known defects and fixed ones do not fail), 1 a case FAILED, 2 wrong version, 5 nothing ran.
# Output: results/matrix.md, results/matrix.csv, results/evidence.jsonl (keys redacted)
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required (the SDK needs it)"'

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
if [ -n "${AIVANA_SDK_SPEC:-}" ]; then
  # --no-deps: the dependencies are already in; only the SDK under test changes. requirements.txt is not edited.
  pip install -q --force-reinstall --no-deps "$AIVANA_SDK_SPEC"
fi
if [ -n "${AIVANA_EXPECT_SDK_VERSION:-}" ]; then
  have="$(python -c 'import aivana; print(aivana.__version__)')"
  if [ "$have" != "$AIVANA_EXPECT_SDK_VERSION" ]; then
    echo "SETUP PROBLEM: installed aivana is $have, expected $AIVANA_EXPECT_SDK_VERSION (AIVANA_EXPECT_SDK_VERSION). Nothing was run."
    exit 2
  fi
fi

echo "aivana $(python -c 'import aivana; print(aivana.__version__)') | live base: ${AIVANA_API_BASE:-https://dev-developers.aivana.ai} | key: $([ -n "${AIVANA_API_KEY:-}" ] && echo set || echo 'not set (live tests skipped)')"
# The exit status is the suite's verdict (see conftest.py), so a failure is not swallowed here: the summary below is
# printed either way, and the script then exits with pytest's status.
status=0
python -m pytest "$@" || status=$?
results="${AIVANA_RESULTS_DIR:-results}"
echo
echo "Matrix:   $(cd "$results" 2>/dev/null && pwd || echo "$results")/matrix.md"
[ -f "$results/evidence.jsonl" ] && echo "Evidence: $(cd "$results" && pwd)/evidence.jsonl"
echo "Exit status: $status"
exit "$status"
