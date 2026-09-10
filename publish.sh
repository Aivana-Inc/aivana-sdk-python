#!/usr/bin/env bash
#
# Build, verify and publish the `aivana` package.
#
#   ./publish.sh            build + check only, uploads nothing (default)
#   ./publish.sh test       upload to TestPyPI
#   ./publish.sh live       upload to PyPI  (irreversible — asks first)
#
# AUTH: never put a token in this file or on the command line. Use one of:
#   ~/.pypirc                                     (recommended)
#   export TWINE_USERNAME=__token__
#   export TWINE_PASSWORD=pypi-...                (this shell only)
# The script neither reads nor prints the token; twine handles it.
#
# A ~/.pypirc holding both accounts looks like this — chmod 600 it:
#
#   [distutils]
#   index-servers = pypi testpypi
#   [pypi]
#     username = __token__
#     password = pypi-AgEIcHl...
#   [testpypi]
#     repository = https://test.pypi.org/legacy/
#     username = __token__
#     password = pypi-AgENdGVzdC...
#
set -euo pipefail
cd "$(dirname "$0")"

TARGET="${1:-check}"
VENV=".venv"

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
die() { printf '\n\033[31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }

case "$TARGET" in check|test|live) ;; *) die "unknown target '$TARGET' (use: check | test | live)";; esac

# --- tooling ---------------------------------------------------------------
say "Preparing build tools"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip build twine pytest httpx pydantic

VERSION=$("$VENV/bin/python" -c "
import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
PKG=$("$VENV/bin/python" -c "
import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['name'])")
echo "  $PKG $VERSION"

# --- gates -----------------------------------------------------------------
say "Running tests"
"$VENV/bin/python" -m pytest tests/ -q

if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo
  git status --short
  echo
  echo "Working tree is dirty. You are about to publish what is on DISK,"
  echo "which is not what is committed."
  read -r -p "Continue anyway? [y/N] " reply
  [ "$reply" = "y" ] || die "stopped — commit first"
fi

# PyPI never lets a version be re-uploaded, even after deletion. Catch it here
# rather than after a failed upload.
taken() {  # taken <index-host> <version>  -> 0 if already published
  # 404 is the only answer that means "free". Anything else — a timeout, a 5xx, a
  # captive-portal redirect — is UNKNOWN, and treating unknown as free would let a
  # network blip wave through the one gate protecting an irreversible upload.
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
         "https://$1/pypi/$PKG/$2/json") || code="000"
  case "$code" in
    200) return 0 ;;
    404) return 1 ;;
    *)   die "cannot reach $1 to check whether $PKG $2 is taken (HTTP $code).
       Not uploading on a guess — retry when the index answers." ;;
  esac
}

# The version we will actually upload. For `live` this is always the real one.
UPLOAD_VERSION="$VERSION"

if [ "$TARGET" = "live" ]; then
  say "Checking $VERSION is still free on pypi.org"
  if taken pypi.org "$VERSION"; then
    die "$PKG $VERSION is already on PyPI. A published version can never be
       reused — bump the version in pyproject.toml."
  fi
  echo "  free"

elif [ "$TARGET" = "test" ]; then
  # TestPyPI is for iterating, so re-running must not be a dead end. If the real
  # version is already up there we upload a .postN of it instead: strictly higher
  # than the base version (so `pip install` picks it up without --pre), while
  # pyproject.toml — and therefore the version reserved on the REAL index — is
  # left untouched. The restore below runs even if the build or upload fails.
  say "Choosing a version for test.pypi.org"
  if taken test.pypi.org "$VERSION"; then
    n=1
    while taken test.pypi.org "${VERSION}.post${n}"; do n=$((n + 1)); done
    UPLOAD_VERSION="${VERSION}.post${n}"
    echo "  $VERSION is already there — uploading $UPLOAD_VERSION"
    echo "  (pyproject.toml stays at $VERSION; the real release is unaffected)"
    cp pyproject.toml .pyproject.toml.bak
    # INT/TERM as well as EXIT: a Ctrl-C during the upload would otherwise leave
    # pyproject.toml holding the .postN version, and the next `live` run would
    # publish THAT number to the real index, permanently.
    trap 'mv -f .pyproject.toml.bak pyproject.toml 2>/dev/null || true' EXIT INT TERM
    sed -i "0,/^version = \".*\"/s//version = \"$UPLOAD_VERSION\"/" pyproject.toml
  else
    echo "  $VERSION is free"
  fi
fi

# --- build -----------------------------------------------------------------
say "Building"
rm -rf dist build ./*.egg-info
"$VENV/bin/python" -m build
"$VENV/bin/python" -m twine check dist/*

say "Contents of the wheel"
"$VENV/bin/python" - <<'PY'
import glob, zipfile
for n in sorted(zipfile.ZipFile(glob.glob("dist/*.whl")[0]).namelist()):
    print("   ", n)
PY

if [ "$TARGET" = "check" ]; then
  say "Built and verified. Nothing uploaded."
  echo "  ./publish.sh test    → TestPyPI"
  echo "  ./publish.sh live    → PyPI"
  exit 0
fi

# --- upload ----------------------------------------------------------------
if [ "$TARGET" = "test" ]; then
  say "Uploading to TestPyPI"
  echo "  Reminder: TestPyPI is a SEPARATE site from PyPI — separate account,"
  echo "  separate token. A pypi.org token is rejected here with a 403."
  echo
  if ! "$VENV/bin/python" -m twine upload --repository testpypi dist/*; then
    cat <<'EOF'

That upload failed.

  400 Bad Request  -> usually this exact file is already uploaded. Check
                      https://test.pypi.org/project/aivana/ before retrying.
  403 Forbidden    -> the token. TestPyPI is a separate site from PyPI:

  * a token from pypi.org does NOT work on test.pypi.org
  * register separately at  https://test.pypi.org/account/register/
  * then make a token at    https://test.pypi.org/manage/account/token/
  * put it in ~/.pypirc under [testpypi], or export TWINE_PASSWORD for this shell

Nothing was published. You can also skip TestPyPI entirely and run
`./publish.sh live` — the build has already been verified.
EOF
    exit 1
  fi
  cat <<EOF

Verify the real install path before going live:

  pip install --index-url https://test.pypi.org/simple/ \\
              --extra-index-url https://pypi.org/simple/ $PKG==$UPLOAD_VERSION
  python -c "import $PKG; print($PKG.__version__, $PKG.api_base)"

(the extra index is needed — httpx and pydantic are not on TestPyPI)
EOF
  exit 0
fi

say "Uploading to PyPI — THIS CANNOT BE UNDONE"
cat <<EOF
  package : $PKG
  version : $VERSION

PyPI never allows a version to be re-uploaded, even after you delete it.
If anything is wrong you will have to ship a new version number.
EOF
read -r -p "Type the version to confirm: " confirm
[ "$confirm" = "$VERSION" ] || die "stopped — got '$confirm', expected '$VERSION'"

"$VENV/bin/python" -m twine upload dist/*

cat <<EOF

Published. Next:
  1. pip install $PKG        (from a clean venv, to confirm)
  2. Replace the account-wide API token with one scoped to '$PKG', and delete the wide one.
  3. git tag v$VERSION && git push origin v$VERSION
  4. Transfer the project to the Aivana org once PyPI approves it.
EOF
