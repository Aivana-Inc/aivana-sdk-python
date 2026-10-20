"""Shared fixtures and the test-matrix reporter for the Aivana Python SDK validation suite.

Every test carries a `case` marker:  @pytest.mark.case("PY-GEN-01", "Generate", "what it checks")
At the end of a run the suite writes:
  results/matrix.md      - the test matrix with pass/fail/defect per case (paste into a report)
  results/matrix.csv     - same, for a spreadsheet
  results/evidence.jsonl - redacted request/response evidence from live tests

Outcome vocabulary in the matrix:
  PASS               SDK behaves as documented
  FAIL               SDK does not behave as documented (unexpected - investigate)
  DEFECT (known)     test asserts documented behaviour, SDK does not meet it; linked finding ID
  FIXED? (re-check)  a known-defect test now passes - the SDK changed, update the report
  SKIP               not run (e.g. live test without AIVANA_API_KEY)
"""
from __future__ import annotations

import csv
import json
import os
import platform
import re
from datetime import datetime
from pathlib import Path

import pytest

import aivana
from aivana import client as _client

HERE = Path(__file__).parent
RESULTS = HERE / "results"

# Live tests default to the dev host - the only one that accepted the team's ai_test_ key
# in the Sept 29 first-call test. Override with AIVANA_API_BASE.
LIVE_BASE = os.environ.get("AIVANA_API_BASE", "https://dev-developers.aivana.ai").rstrip("/")
# aivana 0.3.1 moved the default from developers.aivana.ai to api.aivana.ai (2026-10-11).
DOCUMENTED_DEFAULT_BASE = "https://api.aivana.ai"
OFFLINE_BASE = "https://api.aivana.test"

_rows: dict[str, dict] = {}
_evidence: list[dict] = []


def _redact(obj):
    key = os.environ.get("AIVANA_API_KEY", "")
    s = json.dumps(obj, default=str)
    if key:
        s = s.replace(key, "[REDACTED]")
    s = re.sub(r"ai_(live|test)_[A-Za-z0-9_\-]{6,}", r"ai_\1_[REDACTED]", s)
    return json.loads(s)


def pytest_configure(config):
    config.addinivalue_line("markers", "case(id, area, title): test-matrix entry")
    config.addinivalue_line("markers", "live: needs AIVANA_API_KEY and network")


def pytest_collection_modifyitems(config, items):
    have_key = bool(os.environ.get("AIVANA_API_KEY", "").strip())
    skip_live = pytest.mark.skip(reason="live test: set AIVANA_API_KEY to run")
    for item in items:
        if item.get_closest_marker("live") and not have_key:
            item.add_marker(skip_live)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    # A 429 on a live test says nothing about the behaviour under test: report it as
    # a skip ("rerun later"), not a failure.
    if rep.when == "call" and rep.failed and item.get_closest_marker("live") and _rate_limited(call):
        rep.outcome = "skipped"
        rep.longrepr = (str(item.fspath), item.location[1] or 0,
                        "Skipped: rate-limited (429) by the API - rerun later")
    m = item.get_closest_marker("case")
    if not m:
        return
    cid, area, title = m.args
    row = _rows.setdefault(cid, {
        "id": cid, "area": area, "title": title,
        "mode": "live" if item.get_closest_marker("live") else "offline",
        "result": "", "finding": "", "detail": "",
    })
    xf = item.get_closest_marker("xfail")
    finding = (xf.kwargs.get("reason", "") or "").split(":")[0].strip() if xf else ""
    res, detail = None, ""
    if rep.when == "setup" and rep.skipped:
        res = "SKIP"
        detail = str(rep.longrepr[-1]) if isinstance(rep.longrepr, tuple) else ""
    elif rep.when == "setup" and rep.failed:
        res, detail = "ERROR", "fixture/setup error"
    elif rep.when == "call":
        if hasattr(rep, "wasxfail"):
            res = "DEFECT (known)" if rep.skipped else "FIXED? (re-check)"
        elif rep.failed and xf and "XPASS" in (rep.longreprtext or ""):
            res = "FIXED? (re-check)"
        elif rep.failed:
            res = "FAIL"
            txt = (rep.longreprtext or "").strip().splitlines()
            detail = (item.callspec.id + ": " if hasattr(item, "callspec") else "") + (txt[-1][:200] if txt else "")
        elif rep.skipped:
            res = "SKIP"
            detail = str(rep.longrepr[-1]) if isinstance(rep.longrepr, tuple) else ""
        else:
            res = "PASS"
    if res is None:
        return
    # Parametrised cases share one row; keep the worst outcome.
    rank = {"": 0, "SKIP": 1, "PASS": 2, "DEFECT (known)": 3, "FIXED? (re-check)": 4, "ERROR": 5, "FAIL": 6}
    if rank[res] >= rank[row["result"]]:
        row["result"] = res
        if detail:
            row["detail"] = detail
        if res in ("DEFECT (known)", "FIXED? (re-check)"):
            row["finding"] = finding


def pytest_sessionfinish(session, exitstatus):
    if not _rows:
        return
    RESULTS.mkdir(exist_ok=True)
    rows = sorted(_rows.values(), key=lambda r: r["id"])
    meta = (f"aivana {aivana.__version__} | Python {platform.python_version()} | "
            f"{platform.system()} | live base {LIVE_BASE} | "
            f"key set: {'yes' if os.environ.get('AIVANA_API_KEY') else 'no'} | "
            f"{datetime.now().isoformat(timespec='seconds')}")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    with open(RESULTS / "matrix.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    lines = ["# Aivana Python SDK - validation matrix", "", meta, "",
             "Totals: " + ", ".join(f"{k or 'not run'} {v}" for k, v in sorted(counts.items())), "",
             "| ID | Area | Check | Mode | Result | Finding | Detail |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| {id} | {area} | {title} | {mode} | {result} | {finding} | {detail} |".format(
            **{k: str(v).replace("|", "\\|") for k, v in r.items()}))
    (RESULTS / "matrix.md").write_text("\n".join(lines) + "\n")
    if _evidence:
        with open(RESULTS / "evidence.jsonl", "w") as f:
            for e in _evidence:
                f.write(json.dumps(_redact(e)) + "\n")


# ---------------------------------------------------------------- fixtures

@pytest.fixture
def evidence(request):
    """Call evidence(**fields) inside a live test to record redacted evidence."""
    m = request.node.get_closest_marker("case")
    cid = m.args[0] if m else request.node.name

    def record(**fields):
        _evidence.append({"case": cid, "at": datetime.now().isoformat(timespec="seconds"), **fields})
    return record


@pytest.fixture
def sdk_state():
    """Snapshot and restore the SDK's module-level config around a test."""
    saved = (_client.api_key, _client.api_base, os.environ.get("AIVANA_API_KEY"))
    yield
    _client.api_key, _client.api_base = saved[0], saved[1]
    if saved[2] is None:
        os.environ.pop("AIVANA_API_KEY", None)
    else:
        os.environ["AIVANA_API_KEY"] = saved[2]


@pytest.fixture
def offline(sdk_state, monkeypatch):
    """Clean, network-free SDK: fake base URL, no key in code or env."""
    monkeypatch.delenv("AIVANA_API_KEY", raising=False)
    _client.api_key = None
    aivana.set_api_base(OFFLINE_BASE)
    return OFFLINE_BASE


_last_live = [0.0]
# The dev API enforces a per-minute request limit (the Oct 5 run hit 429 after ~20
# requests in ~65 s). Space live tests out so the limit is not what gets measured.
LIVE_PACE_S = float(os.environ.get("AIVANA_LIVE_PACE", "6"))


@pytest.fixture
def live(sdk_state):
    """SDK pointed at the live dev host, key read from AIVANA_API_KEY as a developer would."""
    import time
    wait = LIVE_PACE_S - (time.time() - _last_live[0])
    if wait > 0:
        time.sleep(wait)
    _client.api_key = None          # rely on the env-var path the docs describe
    aivana.set_api_base(LIVE_BASE)
    yield LIVE_BASE
    _last_live[0] = time.time()


def _rate_limited(call) -> bool:
    return (call.excinfo is not None and call.excinfo.errisinstance(aivana.RateLimitError))


# Cheap defaults for live calls so a full run costs very little credit.
CHEAP = {"effort": "low", "max_tokens": 80}
