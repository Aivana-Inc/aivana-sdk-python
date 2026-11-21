"""Build the standalone download: a new folder with exactly the files a person needs, and a checksum list.

    python tools/package_starter.py NEW_OUTPUT_DIRECTORY

Only an explicit list of files is copied. The package never contains a .env, a private Blueprint, tests, caches,
Git history or anything else that happens to be lying in the source folder. The output folder must not exist yet,
so a release is never mixed with leftovers (an old .env, for example). Zip the folder to publish it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_LICENSE = ROOT.parent.parent / "LICENSE"

FILES = [
    "requirements.txt", ".env.example", ".gitignore", "README.md",
    "blueprints/landscaping.example.json",
    "basic_chat/__init__.py", "basic_chat/__main__.py", "basic_chat/app.py", "basic_chat/blueprint.py", "basic_chat/client.py",
    "basic_chat/config.py", "basic_chat/errors.py", "basic_chat/guard.py", "basic_chat/models.py",
    "public/app.js", "public/conversation.mjs", "public/markdown.mjs", "public/highlight.mjs", "public/render.mjs", "public/typing.mjs",
    "public/index.html", "public/styles.css", "public/assets/aivana-logo.avif", "public/assets/aivana-sparkle.avif", "public/assets/README.md",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(destination: str | Path, source: Path = ROOT, license_file: Path = REPO_LICENSE) -> Path:
    target = Path(destination).resolve()
    target.mkdir(parents=True)  # refuses an existing folder
    checksums: dict[str, str] = {}
    for name in FILES:
        origin = source / name
        if origin.is_symlink() or not origin.is_file():
            raise RuntimeError(f"Release inputs must be regular files: {name}")
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target / name)
        checksums[name] = _sha256(origin)
    shutil.copyfile(license_file, target / "LICENSE")
    checksums["LICENSE"] = _sha256(target / "LICENSE")
    namespace: dict = {}
    exec((source / "basic_chat" / "__init__.py").read_text(encoding="utf-8"), namespace)  # reads __version__ without importing the package
    manifest = {"formatVersion": 1, "version": namespace["__version__"], "sha256": checksums}
    (target / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python tools/package_starter.py NEW_OUTPUT_DIRECTORY")
    print(package(sys.argv[1]))
