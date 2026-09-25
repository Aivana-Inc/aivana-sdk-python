"""`python -m aivana` — the same program as the `aivana` command.

For environments where pip's scripts directory is not on PATH.
"""
import sys

from aivana.cli import main

if __name__ == "__main__":
    sys.exit(main())
