"""The streaming route: what the page receives while an answer is written, and how every way of failing is told."""

from __future__ import annotations

import json
import time

from starlette.responses import JSONResponse

from .conftest import with_blueprint
from .support import KEY, sse


def events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def stream_of(*parts, **options):
    async def respond(entry, request, count):
        return sse(*parts, upstream=holder.get("upstream"), **options)

    holder: dict = {}
    return respond, holder


def test_deltas_arrive_then_one_done_with_validated_usage_and_no_credits(fixture):
    respond, holder = stream_of(
        ("delta", {"text": "Hel"}), ("delta", {"text": "lo"}),
        ("done", {"intent": {"name": "analysis"}, "pending_action": "offer", "latency_ms": 11,
                  "usage": {"input_tokens": 5, "output_tokens": 6, "cached_tokens": 1, "credits": 0.0042}}),
    )
    app = fixture(respond)
    response = app.page.post({"message": "Hi", "settings": {"effort": "low", "webSearch": True, "maxTokens": 400}}, path="/api/chat/stream")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-ndjson; charset=utf-8"
    assert response.headers["x-accel-buffering"] == "no" and response.headers["cache-control"] == "no-store"
    assert events(response) == [
        {"event": "delta", "data": {"text": "Hel"}}, {"event": "delta", "data": {"text": "lo"}},
        {"event": "done", "data": {"context": {"previousIntent": "analysis", "pendingAction": "offer"},
                                   "usage": {"inputTokens": 5, "outputTokens": 6, "latencyMs": 11}}},
    ]
    assert "credits" not in response.text and "0.0042" not in response.text
    body = app.seen[0]["body"]
    assert (body["effort"], body["web_search"], body["max_tokens"]) == ("low", True, 400)


def test_text_is_forwarded_as_it_arrives_not_all_at_the_end(fixture):
    respond, _ = stream_of((0, "delta", {"text": "one "}), (0.4, "delta", {"text": "two "}), (0.4, "delta", {"text": "three"}),
                           (0, "done", {"intent": {"name": "x"}}))
    app = fixture(respond)
    arrivals = []
    started = time.monotonic()
    with app.page.http.stream("POST", "/api/chat/stream", content=json.dumps({"message": "Hi"}),
                              headers={"Origin": app.origin, "Content-Type": "application/json"}) as response:
        for line in response.iter_lines():
            if line.strip():
                arrivals.append((time.monotonic() - started, json.loads(line)["event"]))
    names = [name for _, name in arrivals]
    assert names == ["delta", "delta", "delta", "done"]
    assert arrivals[0][0] < 0.35 and arrivals[2][0] - arrivals[0][0] > 0.6, f"not incremental: {arrivals}"


def test_a_stream_that_breaks_is_never_reported_as_successful(fixture):
    respond, _ = stream_of(("delta", {"text": "partial"}), ("delta", {"text": " more"}),
                           ("done", {"intent": {"name": "x"}}), fail_after=1)
    app = fixture(respond)
    got = events(app.page.post({"message": "Hi"}, path="/api/chat/stream"))
    assert [e["event"] for e in got] == ["delta", "error"], got
    assert "interrupted" in got[-1]["data"]["message"] and "credit" in got[-1]["data"]["message"]


def test_an_error_frame_from_the_api_is_an_error_and_never_a_done(fixture):
    respond, _ = stream_of(("delta", {"text": "partial"}), ("error", {"message": KEY}), ("done", {"intent": {"name": "x"}}))
    got = events(fixture(respond).page.post({"message": "Hi"}, path="/api/chat/stream"))
    assert [e["event"] for e in got] == ["delta", "error"]
    assert KEY not in json.dumps(got)


def test_a_stream_that_ends_without_done_is_a_failure(fixture):
    respond, _ = stream_of(("delta", {"text": "Looks complete"}))
    got = events(fixture(respond).page.post({"message": "Hi"}, path="/api/chat/stream"))
    assert [e["event"] for e in got] == ["delta", "error"]


def test_a_stream_with_no_text_is_a_failure_even_when_done_arrives(fixture):
    for parts in ([("done", {"intent": {"name": "x"}})], [("delta", {"text": "   "}), ("done", {"intent": {"name": "x"}})]):
        respond, _ = stream_of(*parts)
        got = events(fixture(respond).page.post({"message": "Hi"}, path="/api/chat/stream"))
        assert got[-1]["event"] == "error" and all(e["event"] != "done" for e in got)


def test_unknown_events_and_odd_frames_are_ignored(fixture):
    respond, _ = stream_of(("trace", {"secret": KEY}), ("delta", {"text": 5}), ("delta", {}), ("delta", {"text": "Fine", "model": "x"}),
                           ("done", {"intent": "not-an-object", "usage": "nope", "latency_ms": "slow"}))
    got = events(fixture(respond).page.post({"message": "Hi"}, path="/api/chat/stream"))
    assert got == [{"event": "delta", "data": {"text": "Fine"}}, {"event": "done", "data": {"context": {}, "usage": {}}}]
    assert KEY not in json.dumps(got)


def test_an_answer_over_the_limit_is_cut_off_with_an_error(fixture):
    respond, _ = stream_of(*[("delta", {"text": "x" * 5000})] * 4, ("done", {"intent": {"name": "x"}}))
    got = events(fixture(respond).page.post({"message": "Hi"}, path="/api/chat/stream"))
    assert got[-1]["event"] == "error" and all(e["event"] != "done" for e in got)


def test_a_failure_before_any_text_is_one_error_line_with_a_fixed_message(fixture):
    async def respond(entry, request, count):
        return JSONResponse({"error": {"code": "raw_failure", "message": KEY}}, status_code=401)

    app = fixture(respond)
    response = app.page.post({"message": "Hi"}, path="/api/chat/stream")
    got = events(response)
    assert [e["event"] for e in got] == ["error"]
    assert KEY not in response.text and "raw_failure" not in response.text
    assert len(app.seen) == 1, "not sent again"


def test_a_stream_that_runs_past_the_time_limit_is_stopped_and_the_api_call_closed(fixture):
    holder: dict = {}

    async def respond(entry, request, count):
        return sse(("delta", {"text": "start"}), (5, "delta", {"text": "never arrives"}), upstream=holder["upstream"])

    app = fixture(respond, timeout_s=0.5)
    holder["upstream"] = app.upstream
    started = time.monotonic()
    got = events(app.page.post({"message": "Hi"}, path="/api/chat/stream"))
    assert time.monotonic() - started < 3
    assert [e["event"] for e in got] == ["delta", "error"]
    assert app.upstream.closed.wait(2), "giving up must close the connection to Aivana"


def test_a_loaded_blueprint_locks_the_settings_on_the_stream_too_and_keeps_its_own_options(fixture):
    respond, _ = stream_of(("delta", {"text": "ok"}), ("done", {"intent": {"name": "x"}}))
    app = fixture(respond, blueprint=with_blueprint({"effort": "high", "max_tokens": 1000, "temperature": None, "top_p": 0.5}))
    assert app.page.post({"message": "Hi", "settings": {"effort": "low"}}, path="/api/chat/stream").status_code == 400
    assert events(app.page.post({"message": "Hi"}, path="/api/chat/stream"))[-1]["event"] == "done"
    body = app.seen[0]["body"]
    assert (body["effort"], body["max_tokens"], body["top_p"]) == ("high", 1000, 0.5) and "temperature" not in body
