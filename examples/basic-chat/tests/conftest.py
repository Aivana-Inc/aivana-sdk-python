"""Fixtures: an app wired to a stand-in API, using the real SDK."""

from __future__ import annotations

import json
import pathlib
from contextlib import ExitStack

import aivana
import pytest
from aivana import client as sdk

from basic_chat.app import create_app
from basic_chat.client import SdkClient

from .support import KEY, Page, Upstream, answer, serve

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
EXPORTED_BLUEPRINT = json.loads((FIXTURES / "agent-kit-definition.json").read_text(encoding="utf-8"))


def with_blueprint(configuration: dict | None = None, history: str = "session") -> dict:
    """The real Agent Kit export, with some settings changed."""
    definition = json.loads(json.dumps(EXPORTED_BLUEPRINT))
    definition["configuration"].update(configuration or {})
    definition["conversation"] = {"history": history}
    return definition


@pytest.fixture(autouse=True)
def _restore_sdk_settings():
    """The SDK keeps its key and address at module level; leave them as each test found them."""
    before = (sdk.api_key, sdk.api_base)
    yield
    sdk.api_key, sdk.api_base = before


@pytest.fixture
def fixture():
    """`fixture(respond, **app_options)` -> an object with .page, .upstream and .origin, torn down after the test."""
    stack = ExitStack()

    def make(respond=None, *, sdk_timeout: float = 3.0, **options):
        async def default(entry, request, count):
            return answer()

        upstream = Upstream(respond or default)
        api_url = stack.enter_context(serve(upstream.app))
        upstream.url = api_url
        app = create_app(client=SdkClient(KEY, api_url, timeout=sdk_timeout), **options)
        origin = stack.enter_context(serve(app))
        page = Page(origin)
        stack.callback(page.close)

        class Made:
            pass

        made = Made()
        made.page, made.upstream, made.origin, made.app = page, upstream, origin, app
        made.seen = upstream.seen
        return made

    yield make
    stack.close()


__all__ = ["aivana", "with_blueprint", "EXPORTED_BLUEPRINT"]
