"""The page is shared with the Node starter, so it must stay byte-identical, and the server must keep its side of the deal."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

from basic_chat.app import ASSETS, NODE_SOURCE_URL, PUBLIC, PYTHON_SOURCE_URL, create_app

from .conftest import with_blueprint

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from sync_front_end import MANIFEST, describe  # noqa: E402

RESYNC = "Run: python tools/sync_front_end.py PATH_TO_aivana-sdk-node/examples/basic-chat/public"


def test_public_matches_the_recorded_copy_of_the_node_page():
    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
    actual = describe(PUBLIC)
    assert set(actual) == set(recorded["files"]), f"files were added or removed by hand. {RESYNC}"
    changed = sorted(name for name in actual if actual[name] != recorded["files"][name])
    assert not changed, f"edited by hand: {changed}. The page is shared with the Node starter and is changed there. {RESYNC}"
    assert re.fullmatch(r"[0-9a-f]{40}", recorded["node_commit"]) or recorded["node_commit"] == "unknown"


@pytest.mark.skipif(not os.environ.get("AIVANA_NODE_STARTER_DIR"), reason="set AIVANA_NODE_STARTER_DIR to a checkout of aivana-sdk-node to compare")
def test_public_matches_a_checkout_of_the_node_starter():
    node_public = Path(os.environ["AIVANA_NODE_STARTER_DIR"]) / "public"
    assert describe(node_public) == describe(PUBLIC), f"the two starters' pages have drifted apart. {RESYNC}"


def test_every_file_the_server_serves_exists_in_the_copied_page():
    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]
    for route, (name, _) in ASSETS.items():
        assert name in recorded, f"{route} serves {name}, which is not part of the copied page"


def test_the_page_calls_only_routes_the_server_has():
    source = (PUBLIC / "app.js").read_text(encoding="utf-8")
    called = set(re.findall(r"""["'`](/api/[a-z/]+)["'`]""", source))
    assert called == {"/api/config", "/api/chat", "/api/chat/stream"}, called


def test_the_source_link_points_at_this_starter_and_only_that_link_changes(fixture):
    page = fixture().page.http.get("/").text
    original = (PUBLIC / "index.html").read_text(encoding="utf-8")
    assert page.count(PYTHON_SOURCE_URL) == 1 and NODE_SOURCE_URL not in page
    assert page == original.replace(NODE_SOURCE_URL, PYTHON_SOURCE_URL), "nothing else in the page is touched"


@pytest.mark.parametrize("links", [0, 2])
def test_the_server_refuses_to_start_if_the_link_it_rewrites_is_not_there_exactly_once(tmp_path, links):
    shutil.copytree(PUBLIC, tmp_path / "public")
    page = tmp_path / "public" / "index.html"
    text = page.read_text(encoding="utf-8")
    page.write_text(text.replace(NODE_SOURCE_URL, "https://example.com") if links == 0 else text + f'<a href="{NODE_SOURCE_URL}">again</a>', encoding="utf-8")
    class Client:  # noqa: D106
        async def generate(self, **_): ...
        def generate_stream(self, **_): ...
    with pytest.raises(RuntimeError, match="Re-sync"):
        create_app(client=Client(), public_dir=tmp_path / "public")


def test_the_requests_the_page_really_builds_are_accepted(fixture):
    """The exact bodies public/app.js sends: a plain chat with the three settings, and a Blueprint chat with none."""
    plain = fixture()
    body = {"message": "Hi", "history": [], "context": {}, "settings": {"effort": "auto", "webSearch": False, "maxTokens": 800}}
    assert plain.page.post(body).status_code == 200 and plain.page.post(body, path="/api/chat/stream").status_code == 200
    locked = fixture(blueprint=with_blueprint())
    body = {"message": "Hi", "history": [], "context": {}, "settings": {}}
    assert locked.page.post(body).status_code == 200


def test_the_config_has_everything_the_page_checks_before_it_will_start(fixture):
    for options in ({}, {"blueprint": with_blueprint(), "blueprint_name": "Helper"}, {"blueprint": with_blueprint({}, "none")}):
        config = fixture(**options).page.http.get("/api/config").json()
        assert isinstance(config["blueprintLoaded"], bool) and isinstance(config["webSearch"], bool)
        assert config["history"] in ("session", "none")
        if config["blueprintLoaded"]:
            assert set(config["blueprint"]) <= {"name", "purpose", "effort", "maxTokens"}
            assert isinstance(config["blueprint"]["purpose"], str) and config["blueprint"]["effort"] in ("auto", "low", "medium", "high")
