"""Copy the page from the Node starter and record exactly what was copied.

The two starters share one page (public/): the browser code is the same for both, and only the server differs.
So the page is never edited here. To take a change, make it in aivana-sdk-node, then run:

    python tools/sync_front_end.py /path/to/aivana-sdk-node/examples/basic-chat/public

That replaces public/ with the Node starter's files and rewrites FRONT_END.json, which tests/test_front_end.py
checks, so an edit made here by hand (or a half-finished sync) fails the tests instead of drifting quietly.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
MANIFEST = ROOT / "FRONT_END.json"
SOURCE_NAME = "Aivana-Inc/aivana-sdk-node, examples/basic-chat/public"


def describe(directory: Path) -> dict[str, str]:
    """Every file under `directory` (relative path -> SHA-256 of its bytes)."""
    return {
        str(path.relative_to(directory)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def commit_of(source: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True, check=True, timeout=10)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("Usage: python tools/sync_front_end.py PATH_TO_NODE_STARTER_public_FOLDER", file=sys.stderr)
        return 2
    source = Path(argv[0]).resolve()
    if not (source / "index.html").is_file() or not (source / "app.js").is_file():
        print("That folder does not look like the Node starter's public/ folder (no index.html and app.js).", file=sys.stderr)
        return 1
    shutil.rmtree(PUBLIC)
    shutil.copytree(source, PUBLIC)
    manifest = {"source": SOURCE_NAME, "node_commit": commit_of(source), "files": describe(PUBLIC)}
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Copied {len(manifest['files'])} files from {source} and rewrote FRONT_END.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
