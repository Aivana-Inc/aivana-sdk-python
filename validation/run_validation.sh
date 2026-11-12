#!/usr/bin/env bash
# Aivana Python SDK validation - one command.
#   bash run_validation.sh            # offline checks only (free, no key)
#   export AIVANA_API_KEY=ai_test_... && bash run_validation.sh    # + live checks on the dev host
#   (or put AIVANA_API_KEY=... in a .env file here; it is gitignored and loaded below)
# Optional: AIVANA_API_BASE=https://... to point live checks somewhere else.
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

echo "aivana $(python -c 'import aivana; print(aivana.__version__)') | live base: ${AIVANA_API_BASE:-https://dev-developers.aivana.ai} | key: $([ -n "${AIVANA_API_KEY:-}" ] && echo set || echo 'not set (live tests skipped)')"
python -m pytest "$@" || true
echo
echo "Matrix:   $(pwd)/results/matrix.md"
[ -f results/evidence.jsonl ] && echo "Evidence: $(pwd)/results/evidence.jsonl"
