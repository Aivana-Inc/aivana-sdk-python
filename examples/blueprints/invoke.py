"""Candidate source checkout only; do not enable before verified API rollout."""
import os
import re
import sys

import aivana


def main():
    names = ("AIVANA_API_KEY", "AIVANA_API_BASE", "AIVANA_BLUEPRINT_ID", "AIVANA_BLUEPRINT_VERSION")
    if not all(os.environ.get(name) for name in names):
        raise SystemExit("Set " + ", ".join(names) + ".")
    value = os.environ["AIVANA_BLUEPRINT_VERSION"]
    if value != "latest" and not re.fullmatch(r"[1-9][0-9]*", value):
        raise SystemExit('AIVANA_BLUEPRINT_VERSION must be a positive integer or explicit "latest".')
    version = value if value == "latest" else int(value)
    aivana.api_key = os.environ["AIVANA_API_KEY"]
    aivana.api_base = os.environ["AIVANA_API_BASE"]
    arguments = dict(id=os.environ["AIVANA_BLUEPRINT_ID"], version=version,
                     prompt="Explain DNS resolution in three short bullets.", intelligence_trace=True)
    try:
        if "--stream" in sys.argv:
            for chunk in aivana.blueprints.stream(**arguments):
                if chunk.event == "delta":
                    print(chunk.delta, end="", flush=True)
                if chunk.event == "done":
                    print("\nResolved Blueprint:", chunk.data["blueprint"])
        else:
            result = aivana.blueprints.generate(**arguments)
            print(result.answer)
            print("Resolved Blueprint:", result.blueprint)
    except aivana.AivanaError as error:
        raise SystemExit(f"Blueprint request failed ({error.code}). No automatic retry or Generate fallback was made.") from None


if __name__ == "__main__":
    main()
