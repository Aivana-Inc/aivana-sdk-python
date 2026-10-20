#!/usr/bin/env bash
# Clean-install checks for the `aivana` package, as an external developer installs it.
#   bash install_check.sh              # every documented install path, no key needed
#   (with AIVANA_API_KEY set, or in .env, each install also answers one cheap live question)
# Everything happens in a throwaway directory: nothing is installed into your own environment,
# and pipx/uv use their own temporary homes and caches so every install really is fresh.
# Output: results/install.md
set -uo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then set -a; source .env; set +a; fi

VERSION="${AIVANA_VERSION:-$(sed -n 's/^aivana==//p' requirements.txt)}"
LIVE_BASE="${AIVANA_API_BASE:-https://dev-developers.aivana.ai}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export UV_CACHE_DIR="$WORK/uv-cache" UV_PYTHON_INSTALL_DIR="$WORK/uv-python" PIP_NO_CACHE_DIR=1
OUT=results/install.md
mkdir -p results
rows=()
pass=0; fail=0

record() {   # id, check, result, detail
  rows+=("| $1 | $2 | $3 | ${4//|/\\|} |")
  if [ "$3" = PASS ]; then pass=$((pass+1)); else fail=$((fail+1)); fi
  printf '%-10s %-5s %s\n' "$1" "$3" "$2"
}

live_ask() {   # binary... -> prints "exit N"
  [ -n "${AIVANA_API_KEY:-}" ] || { echo "skipped (no key)"; return; }
  AIVANA_API_BASE="$LIVE_BASE" "$@" "Reply with the single word: ok" --effort low --max-tokens 20 -q \
    </dev/null >"$WORK/ans" 2>"$WORK/err"
  echo "exit $? answer='$(tr -d '\n' <"$WORK/ans" | cut -c1-40)'"
}

# --- pip into a fresh virtual environment, on each supported Python -------------------
for py in 3.10 3.12 3.13 3.14; do
  id="INS-PIP-${py/./}"
  venv="$WORK/venv-$py"
  if ! uv venv -q --seed -p "$py" "$venv" 2>"$WORK/err"; then
    record "$id" "pip install aivana==$VERSION on Python $py (fresh venv)" FAIL "could not create Python $py: $(head -c 200 "$WORK/err")"
    continue
  fi
  if "$venv/bin/python" -m pip install -q "aivana==$VERSION" 2>"$WORK/err"; then
    ver="$("$venv/bin/aivana" --version 2>&1)"
    imp="$("$venv/bin/python" -c 'import aivana; from aivana import generate, generate_async, Chat, AivanaError; print(aivana.__version__)' 2>&1)"
    deps="$("$venv/bin/python" -m pip list --format=freeze 2>/dev/null | cut -d= -f1 | tr '\n' ' ')"
    live="$(live_ask "$venv/bin/aivana")"
    if [ "$ver" = "aivana $VERSION" ] && [ "$imp" = "$VERSION" ] && [[ "$live" != exit\ [1-9]* ]]; then
      record "$id" "pip install aivana==$VERSION on Python $py (fresh venv)" PASS "$ver; import OK; live: $live; installed: $deps"
    else
      record "$id" "pip install aivana==$VERSION on Python $py (fresh venv)" FAIL "version='$ver' import='$imp' live: $live"
    fi
  else
    record "$id" "pip install aivana==$VERSION on Python $py (fresh venv)" FAIL "$(tail -c 300 "$WORK/err")"
  fi
done

# --- below the documented minimum: pip must refuse, not install something broken --------
venv="$WORK/venv-3.9"
if uv venv -q --seed -p 3.9 "$venv" 2>/dev/null; then
  if "$venv/bin/python" -m pip install -q "aivana==$VERSION" >"$WORK/out" 2>&1; then
    record INS-PIP-39 "Python 3.9 (below the documented 3.10) is refused by pip" FAIL "pip installed it"
  elif grep -qi 'requires-python\|requires a different python\|no matching distribution' "$WORK/out"; then
    record INS-PIP-39 "Python 3.9 (below the documented 3.10) is refused by pip" PASS "$(grep -m1 -i 'requires-python\|requires a different python\|no matching distribution' "$WORK/out" | cut -c1-160)"
  else
    record INS-PIP-39 "Python 3.9 (below the documented 3.10) is refused by pip" FAIL "pip failed for another reason: $(tail -c 200 "$WORK/out")"
  fi
else
  record INS-PIP-39 "Python 3.9 (below the documented 3.10) is refused by pip" FAIL "could not create Python 3.9"
fi

# --- pipx install aivana (README / Docs > Command Line, step 1) ------------------------
export PIPX_HOME="$WORK/pipx-home" PIPX_BIN_DIR="$WORK/pipx-bin" PIPX_MAN_DIR="$WORK/pipx-man"
if pipx install -q "aivana==$VERSION" >"$WORK/out" 2>&1; then
  ver="$("$PIPX_BIN_DIR/aivana" --version 2>&1)"
  help_ok="$("$PIPX_BIN_DIR/aivana" --help 2>&1 | grep -c 'AIVANA_API_KEY')"
  live="$(live_ask "$PIPX_BIN_DIR/aivana")"
  if [ "$ver" = "aivana $VERSION" ] && [ "$help_ok" -ge 1 ] && [[ "$live" != exit\ [1-9]* ]]; then
    record INS-PIPX "pipx install aivana puts a working \`aivana\` on PATH" PASS "$ver; live: $live"
  else
    record INS-PIPX "pipx install aivana puts a working \`aivana\` on PATH" FAIL "version='$ver' live: $live"
  fi
else
  record INS-PIPX "pipx install aivana puts a working \`aivana\` on PATH" FAIL "$(tail -c 300 "$WORK/out")"
fi

# --- uvx aivana "..." (README / Docs: try it without installing) -----------------------
ver="$(uvx -q --from "aivana==$VERSION" aivana --version 2>&1)"
live="$(live_ask uvx -q --from "aivana==$VERSION" aivana)"
if [ "$ver" = "aivana $VERSION" ] && [[ "$live" != exit\ [1-9]* ]]; then
  record INS-UVX "uvx --from aivana==$VERSION aivana runs without installing" PASS "$ver; live: $live"
else
  record INS-UVX "uvx --from aivana==$VERSION aivana runs without installing" FAIL "version='$ver' live: $live"
fi
latest="$(uvx -q aivana --version 2>&1)"
if [ "$latest" = "aivana $VERSION" ]; then
  record INS-UVX-LATEST "The Docs' exact form \`uvx aivana\` resolves to the latest release ($VERSION)" PASS "$latest"
else
  record INS-UVX-LATEST "The Docs' exact form \`uvx aivana\` resolves to the latest release ($VERSION)" FAIL "got '$latest' (is $VERSION the latest on PyPI?)"
fi

{
  echo "# Aivana - clean install checks"
  echo
  echo "aivana $VERSION | $(uname -s) $(uname -m) | uv $(uv --version | cut -d' ' -f2) | pipx $(pipx --version) | live: $([ -n "${AIVANA_API_KEY:-}" ] && echo "$LIVE_BASE" || echo 'skipped (no key)') | $(date '+%Y-%m-%dT%H:%M:%S')"
  echo
  echo "Totals: PASS $pass, FAIL $fail"
  echo
  echo "| ID | Check | Result | Detail |"
  echo "|---|---|---|---|"
  printf '%s\n' "${rows[@]}"
} >"$OUT"
echo
echo "Install results: $(pwd)/$OUT"
