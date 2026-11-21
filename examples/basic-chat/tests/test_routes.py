"""The chat routes, through the real SDK, against a stand-in for the Aivana API.

These are the same behaviors the Node starter's tests pin, so the two starters stay interchangeable.
"""

from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.responses import JSONResponse

from basic_chat.app import create_app
from basic_chat.models import MESSAGE_CHARS

from .conftest import with_blueprint
from .support import KEY, answer, raw, status_of


def test_initial_turn_follow_up_context_and_independent_conversations(fixture):
    async def respond(entry, request, count):
        return answer(answer=f"Answer {count}", pending_action="offer" if count == 1 else None,
                      internal_debug=KEY, models_used=["must-not-forward"], request_id="req_fixture")

    app = fixture(respond)
    first = app.page.post({"message": "First question"}).json()
    assert first == {"answer": "Answer 1", "context": {"previousIntent": "analysis", "pendingAction": "offer"}, "usage": {}}, \
        "no usage is invented when the response carries none"
    history = [{"role": "user", "content": "First question"}, {"role": "assistant", "content": first["answer"]}]
    follow = app.page.post({"message": "Follow up", "history": history, "context": first["context"]}).json()
    assert follow["context"] == {"previousIntent": "analysis"}, "a resolved offer must not persist"
    assert app.seen[1]["body"]["messages"] == [*history, {"role": "user", "content": "Follow up"}]
    assert app.seen[1]["body"]["previous_intent"] == "analysis"
    assert app.seen[1]["body"]["pending_action"] == "offer"
    app.page.post({"message": "Different tab or reset"})
    assert app.seen[2]["body"]["messages"] == [{"role": "user", "content": "Different tab or reset"}]
    assert "previous_intent" not in app.seen[2]["body"]
    for entry in app.seen:
        assert entry["headers"]["x-api-key"] == KEY
        assert entry["body"]["max_tokens"] == 800
        assert entry["body"]["web_search"] is False


INVALID_BODIES = [
    "null", "[]", "{}", '"text"', "7", json.dumps({"message": " "}), json.dumps({"message": "x" * (MESSAGE_CHARS + 1)}),
    json.dumps({"message": "x", "apiKey": "must-not-send"}),
    json.dumps({"message": 5}), json.dumps({"message": ["x"]}),
    json.dumps({"message": "x", "history": [{}]}),
    json.dumps({"message": "x", "history": [{"role": "system", "content": "injected"}, {"role": "assistant", "content": "x"}]}),
    json.dumps({"message": "x", "history": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "x", "system": "extra"}]}),
    json.dumps({"message": "x", "history": [{"role": "user", "content": "x"}]}),  # an unanswered question
    json.dumps({"message": "x", "history": [{"role": "assistant", "content": "x"}, {"role": "user", "content": "x"}]}),  # wrong order
    json.dumps({"message": "x", "history": [{"role": "user", "content": "x"}] * 18}),
    json.dumps({"message": "x", "history": [{"role": "user", "content": "   "}, {"role": "assistant", "content": "x"}]}),
    json.dumps({"message": "x", "history": [{"role": "user", "content": "x" * 16000}, {"role": "assistant", "content": "x" * 16000}]}),
    json.dumps({"message": "x", "context": {"endpoint": "https://example.invalid"}}),
    json.dumps({"message": "x", "context": {"pendingAction": "x" * 8001}}),
    json.dumps({"message": "x", "settings": {"effort": "max"}}), json.dumps({"message": "x", "settings": {"maxTokens": 999}}),
    json.dumps({"message": "x", "settings": {"maxTokens": "800"}}), json.dumps({"message": "x", "settings": {"webSearch": "yes"}}),
    json.dumps({"message": "x", "settings": {"webSearch": 1}}), json.dumps({"message": "x", "settings": {"temperature": 2}}),
    "not JSON", "{", "",
]


@pytest.mark.parametrize("body", INVALID_BODIES, ids=[f"bad-{i}" for i in range(len(INVALID_BODIES))])
def test_invalid_requests_never_reach_the_sdk_and_are_never_echoed(fixture, body):
    app = fixture()
    for path in ("/api/chat", "/api/chat/stream"):
        response = app.page.post(body, path=path)
        assert response.status_code == 400, body[:60]
        assert response.json()["error"]["code"] == "invalid_request"
        assert set(response.json()) == {"error"} and set(response.json()["error"]) == {"code", "message"}
        assert "x" * 50 not in response.text, "what the person sent must never be repeated back"
    assert app.seen == []


def test_a_request_over_the_size_cap_is_refused_before_it_is_read(fixture):
    app = fixture()
    large = app.page.post({"message": "x" * 270_000})
    assert large.status_code == 413
    assert large.json()["error"]["code"] == "request_too_large"
    assert app.seen == []
    assert app.page.post({"message": "still works"}).status_code == 200, "the server is fine afterwards"


def test_only_the_fixed_page_files_are_ever_served(fixture):
    app = fixture()
    for path in ("/", "/app.js", "/styles.css", "/assets/aivana-logo.avif", "/assets/aivana-sparkle.avif", "/conversation.mjs",
                 "/markdown.mjs", "/highlight.mjs", "/render.mjs", "/typing.mjs"):
        response = app.page.http.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "no-store"
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "set-cookie" not in response.headers
        if path.endswith(".avif"):
            assert response.headers["content-type"] == "image/avif" and len(response.content) > 0
        else:
            assert KEY not in response.text
    for path in ("/.env", "/.env.example", "/requirements.txt", "/basic_chat/app.py", "/basic_chat/__main__.py", "/public/app.js",
                 "/assets/README.md", "/blueprints/landscaping.example.json", "/blueprint-definition.json", "/pyproject.toml",
                 "/%2eenv", "/%2e%2e/%2e%2e/etc/passwd", "/app.js/", "/app.js%00", "/APP.JS", "/api/chat/"):
        assert app.page.http.get(path).status_code == 404, path
    # Odd paths go over a raw socket: an HTTP client would tidy them up before sending, hiding what the server does.
    host = app.origin.removeprefix("http://").encode()
    for target in (b"/../../etc/passwd", b"/..%2fbasic_chat/app.py", b"/%252e%252e/%252e%252e/etc/passwd", b"/app.js/../app.py",
                   b"//app.js", b"///app.js", b"/app.js//", b"/./app.js", b"/x/../app.js", b"/app.js?x=1#y"):
        reply, _ = raw(app.origin, b"GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % (target, host))
        assert status_of(reply) in (200, 400, 404), target
        assert b"root:" not in reply and b"create_app" not in reply, target
        if target != b"/app.js?x=1#y":
            assert status_of(reply) != 200, target
    assert app.seen == []


def test_other_methods_on_known_paths_are_refused_and_unknown_paths_are_not_found(fixture):
    app = fixture()
    for method, path in (("GET", "/api/chat"), ("GET", "/api/chat/stream"), ("OPTIONS", "/api/chat"), ("PUT", "/api/chat"), ("DELETE", "/api/chat/stream")):
        response = app.page.http.request(method, path)
        assert response.status_code == 405, (method, path)
        assert response.json()["error"]["code"] == "method_not_allowed" and response.headers["allow"] == "POST"
    for method, path in (("POST", "/"), ("HEAD", "/"), ("POST", "/api/config"), ("GET", "/api"), ("GET", "/docs"), ("GET", "/openapi.json")):
        assert app.page.http.request(method, path).status_code == 404, (method, path)
    assert app.seen == []


def test_cross_origin_wrong_host_form_and_preflight_requests_cannot_spend_credit(fixture):
    app = fixture()
    other = {"Origin": "https://other.invalid"}
    for headers in (other, {"Origin": "null"}, {"Origin": ""}, {"Host": "other.invalid", "Origin": "http://other.invalid"},
                    {"Sec-Fetch-Site": "cross-site"}, {"Host": "127.0.0.1:1", "Origin": "http://127.0.0.1:1"}):
        assert app.page.post({"message": "x"}, headers=headers).status_code == 403, headers
    # No Origin header at all (a script, not a page) is refused too.
    reply, _ = raw(app.origin, b"POST /api/chat HTTP/1.1\r\nHost: %s\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: 15\r\n\r\n{\"message\":\"x\"}"
                   % app.origin.removeprefix("http://").encode())
    assert status_of(reply) == 403
    assert app.page.post({"message": "x"}, headers={"Content-Type": "text/plain"}).status_code == 415
    assert app.page.post({"message": "x"}, headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 415
    assert app.page.http.get("/", headers={"Host": "evil.example"}).status_code == 403, "DNS rebinding: even the page is refused"
    assert app.page.http.get("/api/config", headers={"Host": "evil.example"}).status_code == 403
    assert app.seen == []


def test_localhost_is_an_accepted_name_and_a_json_charset_is_fine(fixture):
    app = fixture()
    port = app.origin.rsplit(":", 1)[1]
    ok = app.page.post({"message": "x"}, headers={"Host": f"localhost:{port}", "Origin": f"http://localhost:{port}",
                                                 "Content-Type": "application/json; charset=utf-8"})
    assert ok.status_code == 200


UPSTREAM_ERRORS = [(401, "raw_failure", 502, "authentication_failed"), (402, "insufficient_credit", 402, "insufficient_credit"),
                   (403, "raw_failure", 403, "access_denied"), (400, "raw_failure", 400, "invalid_request"),
                   (422, "invalid_request", 400, "invalid_request"), (429, "raw_failure", 429, "rate_limited"),
                   (500, "raw_failure", 502, "unavailable"), (502, "raw_failure", 502, "unavailable"), (418, "raw_failure", 502, "unavailable")]


def test_upstream_errors_use_fixed_messages_never_leak_raw_details_and_never_retry(fixture):
    state = {"status": 401, "code": "raw_failure"}

    async def respond(entry, request, count):
        return JSONResponse({"error": {"code": state["code"], "message": KEY, "request_id": KEY}, "debug": KEY},
                            status_code=state["status"], headers={"Retry-After": "0"})

    app = fixture(respond)
    for upstream_status, code, expected_status, expected_code in UPSTREAM_ERRORS:
        state.update(status=upstream_status, code=code)
        for path in ("/api/chat",):
            response = app.page.post({"message": "x"}, path=path)
            assert response.status_code == expected_status, upstream_status
            assert response.json()["error"]["code"] == expected_code
            assert KEY not in response.text and "raw_failure" not in response.text
    assert len(app.seen) == len(UPSTREAM_ERRORS), "one attempt each: a rate limit is not retried behind the person's back"


def test_only_a_per_minute_rate_limit_is_ever_asked_again(fixture):
    """The SDK retries one thing: Aivana refusing for a per-minute limit, before any work. Nothing else is repeated."""
    state = {"fail": 1, "status": 429, "code": "rate_limit_exceeded"}

    async def respond(entry, request, count):
        if count <= state["fail"]:
            return JSONResponse({"error": {"code": state["code"], "message": "x"}}, status_code=state["status"], headers={"Retry-After": "0"})
        return answer()

    app = fixture(respond)
    assert app.page.post({"message": "x"}).status_code == 200 and len(app.seen) == 2, "a per-minute limit is retried once, then succeeds"
    for status, code in ((429, "quota_reached"), (429, "spend_limit_reached"), (500, "internal_error"), (502, "upstream"), (503, "unavailable")):
        before = len(app.seen)
        state.update(fail=10**6, status=status, code=code)
        assert app.page.post({"message": "x"}).status_code != 200
        assert len(app.seen) == before + 1, f"{status} {code} must not be repeated"
    state.update(fail=10**6, status=429, code="rate_limit_exceeded")
    before = len(app.seen)
    assert app.page.post({"message": "x"}).status_code == 429 and len(app.seen) == before + 3, "at most two retries, then the person is told"


@pytest.mark.parametrize("result", [None, "", "   ", {}, 5, "x" * 16001])
def test_malformed_and_empty_answers_fail_without_entering_a_follow_up(fixture, result):
    state = {"answer": result}

    async def respond(entry, request, count):
        return answer(answer=state["answer"])

    app = fixture(respond)
    response = app.page.post({"message": "x"})
    assert response.status_code == 502 and response.json()["error"]["code"] == "unavailable"
    state["answer"] = "Recovered"
    assert app.page.post({"message": "new request"}).json()["answer"] == "Recovered"
    assert app.seen[-1]["body"]["messages"] == [{"role": "user", "content": "new request"}]


def test_an_answer_the_sdk_cannot_read_is_a_fixed_failure(fixture):
    async def respond(entry, request, count):
        return JSONResponse({"unexpected": "shape"})

    response = fixture(respond).page.post({"message": "x"})
    assert response.status_code == 502 and response.json()["error"]["code"] == "unavailable"


def test_a_stalled_upstream_request_times_out_and_frees_its_slot(fixture):
    state = {"hang": True}

    async def respond(entry, request, count):
        return None if state["hang"] else answer()

    app = fixture(respond, timeout_s=0.3)
    response = app.page.post({"message": "x"})
    assert response.status_code == 504 and response.json()["error"]["code"] == "timeout"
    assert app.upstream.closed.wait(2), "giving up closes the connection to Aivana"
    state["hang"] = False
    assert app.page.post({"message": "later"}).status_code == 200


def test_disconnecting_the_browser_cancels_the_upstream_request(fixture):
    async def respond(entry, request, count):
        return None

    app = fixture(respond)
    host, port = app.origin.removeprefix("http://").split(":")
    body = json.dumps({"message": "x"}).encode()
    sock = socket.create_connection((host, int(port)))
    sock.sendall(b"POST /api/chat HTTP/1.1\r\nHost: %s:%s\r\nOrigin: %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
                 % (host.encode(), port.encode(), app.origin.encode(), len(body), body))
    for _ in range(200):
        if app.seen:
            break
        import time
        time.sleep(0.01)
    assert app.seen, "the request reached the API"
    sock.close()  # the browser's tab closes
    assert app.upstream.closed.wait(2), "the call to Aivana was not cancelled"


def test_concurrency_is_bounded_without_sharing_conversation_state(fixture):
    async def respond(entry, request, count):
        await app.upstream.wait_for_release()
        return answer()

    app = fixture(respond)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(app.page.post, {"message": "one"})
        second = pool.submit(app.page.post, {"message": "two"})
        for _ in range(300):
            if len(app.seen) == 2:
                break
            import time
            time.sleep(0.01)
        assert len(app.seen) == 2
        third = app.page.post({"message": "three"})
        assert third.status_code == 429 and third.json()["error"]["code"] == "busy"
        app.upstream.release.set()
        assert first.result().status_code == 200 and second.result().status_code == 200
    assert [len(entry["body"]["messages"]) for entry in app.seen] == [1, 1]
    assert app.page.post({"message": "four"}).status_code == 200, "slots are given back"


def test_settings_from_the_page_reach_the_wire_and_nothing_else_does(fixture):
    app = fixture()
    ok = app.page.post({"message": "Hi", "settings": {"effort": "high", "webSearch": True, "maxTokens": 1600}})
    assert ok.status_code == 200
    body = app.seen[0]["body"]
    assert (body["effort"], body["web_search"], body["max_tokens"]) == ("high", True, 1600)
    assert set(body) == {"mode", "messages", "effort", "web_search", "max_tokens"}, "no stray field reaches the API"


def test_usage_and_response_time_are_forwarded_only_when_the_response_carries_them_and_never_credits(fixture):
    state = {"extra": {"usage": {"input_tokens": 12, "output_tokens": 34, "cached_tokens": 5, "credits": 0.000417}, "latency_ms": 1235}}

    async def respond(entry, request, count):
        return answer(**state["extra"])

    app = fixture(respond)
    body = app.page.post({"message": "Hello"}).json()
    assert body["usage"] == {"inputTokens": 12, "outputTokens": 34, "latencyMs": 1235}
    assert "credits" not in json.dumps(body) and "0.000417" not in json.dumps(body)
    state["extra"] = {"usage": {"input_tokens": -1, "output_tokens": 0, "credits": 1}}
    assert app.page.post({"message": "Hello"}).json()["usage"] == {"outputTokens": 0}, "a negative count is dropped; zero is real"
    state["extra"] = {"usage": {"input_tokens": 3}}
    assert app.page.post({"message": "Hello"}).json()["usage"] == {"inputTokens": 3}, "only what was sent: no invented zeros"


def test_a_client_is_required():
    with pytest.raises(ValueError, match="client is required"):
        create_app(client=None)
    with pytest.raises(ValueError, match="client is required"):
        create_app(client=object())


# ---- Blueprints ----------------------------------------------------------------------------------------------------

def test_an_agent_kit_export_reaches_the_wire_unchanged(fixture):
    app = fixture(blueprint=with_blueprint())
    assert app.page.post({"message": "Hello"}).status_code == 200
    assert app.seen[0]["body"] == {"mode": "aivana_mmi", "system": "Be clear", "effort": "auto", "web_search": False, "temperature": 0.7,
                                   "max_tokens": 2048, "response_format": {"type": "text"}, "messages": [{"role": "user", "content": "Hello"}]}


def test_blueprint_zeroes_null_omissions_and_stop_sequences_survive(fixture):
    app = fixture(blueprint=with_blueprint({"system": "Private instructions", "effort": "high", "web_search": True, "temperature": None,
                                            "top_p": 0, "max_tokens": None, "stop_sequences": [" END ", "STOP"]}))
    app.page.post({"message": "Hello"})
    body = app.seen[0]["body"]
    assert body["system"] == "Private instructions" and body["effort"] == "high" and body["web_search"] is True and body["top_p"] == 0
    assert body["stop_sequences"] == [" END ", "STOP"]
    for key in ("temperature", "max_tokens", "purpose", "blueprint", "knowledge"):
        assert key not in body, key
    zero = fixture(blueprint=with_blueprint({"temperature": 0, "top_p": None, "max_tokens": 1}))
    zero.page.post({"message": "Hello"})
    assert zero.seen[0]["body"]["temperature"] == 0 and zero.seen[0]["body"]["max_tokens"] == 1 and "top_p" not in zero.seen[0]["body"]


@pytest.mark.parametrize("mode", ["none", "session"])
def test_history_none_blocks_prior_messages_and_continuation_state_while_session_keeps_both(fixture, mode):
    history = [{"role": "user", "content": "Private earlier turn"}, {"role": "assistant", "content": "Earlier answer"}]

    async def respond(entry, request, count):
        return answer(pending_action="next")

    app = fixture(respond, blueprint=with_blueprint({}, mode))
    response = app.page.post({"message": "Current", "history": history, "context": {"previousIntent": "old", "pendingAction": "old action"}})
    assert response.status_code == 200
    body = app.seen[0]["body"]
    assert body["messages"] == [*(history if mode == "session" else []), {"role": "user", "content": "Current"}]
    assert body.get("previous_intent") == ("old" if mode == "session" else None)
    assert body.get("pending_action") == ("old action" if mode == "session" else None)
    assert response.json()["context"] == ({"previousIntent": "analysis", "pendingAction": "next"} if mode == "session" else {})


def test_blueprint_public_flags_reveal_no_instructions_and_browsers_cannot_override_settings(fixture):
    app = fixture(blueprint=with_blueprint({"system": "PRIVATE_INSTRUCTIONS"}, "none"))
    response = app.page.http.get("/api/config")
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"blueprintLoaded": True, "history": "none", "webSearch": False,
                               "blueprint": {"purpose": "Help users", "effort": "auto", "maxTokens": 2048}}
    assert "PRIVATE_INSTRUCTIONS" not in response.text
    for key in ("system", "blueprint", "configuration", "webSearch", "historyMode"):
        assert app.page.post({"message": "Hello", key: "override"}).status_code == 400, key
    for path in ("/api/chat", "/api/chat/stream"):
        locked = app.page.post({"message": "Hello", "settings": {"effort": "low"}}, path=path)
        assert locked.status_code == 400 and "locked" in locked.json()["error"]["message"], path
    assert app.page.post({"message": "Hello", "settings": {}}).status_code == 200, "no overrides is fine"
    assert len(app.seen) == 1
    with pytest.raises(Exception, match="Effort"):
        create_app(client=object.__new__(type("C", (), {"generate": lambda s: None, "generate_stream": lambda s: None})),
                   blueprint=with_blueprint({"effort": "typo"}))


def test_a_blueprints_name_is_shared_only_with_a_loaded_blueprint(fixture):
    named = fixture(blueprint=with_blueprint({"system": "PRIVATE_INSTRUCTIONS"}), blueprint_name="  Juniper Landscaping Assistant ")
    config = named.page.http.get("/api/config").json()
    assert config["blueprint"]["name"] == "Juniper Landscaping Assistant"
    assert config["blueprint"]["purpose"] == "Help users", "the purpose is still there beside the name"
    assert "PRIVATE_INSTRUCTIONS" not in json.dumps(config)
    unnamed = fixture(blueprint=with_blueprint(), blueprint_name="   ")
    assert "name" not in unnamed.page.http.get("/api/config").json()["blueprint"], "a blank name is no name"
    plain = fixture(blueprint_name="Ignored without a Blueprint")
    assert plain.page.http.get("/api/config").json() == {"blueprintLoaded": False, "history": "session", "webSearch": False}
    with pytest.raises(Exception, match="AIVANA_BLUEPRINT_NAME"):
        fixture(blueprint=with_blueprint(), blueprint_name="two\nlines")


def test_an_unexpected_bug_is_a_fixed_500_that_ends_normally_and_never_shows_or_logs_the_exception_text(fixture, monkeypatch, caplog):
    leak = "-".join(["what", "the", "person", "typed"]) + KEY  # built at run time: a traceback prints source lines, which are code, not data

    def broken(_):
        raise RuntimeError(leak)

    monkeypatch.setattr("basic_chat.app.thaw", broken)
    app = fixture()
    for path in ("/api/chat", "/api/chat/stream"):
        response = app.page.post({"message": "x"}, path=path)
        assert response.status_code == 500 and response.json()["error"]["code"] == "internal_error"
        assert response.headers["connection"] == "close" and "no-store" in response.headers["cache-control"]
        assert leak not in response.text and KEY not in response.text
    assert app.seen == []
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "RuntimeError" in logged and "/api/chat" in logged, "the terminal says what kind of error, and where"
    assert leak not in logged and KEY not in logged, "but never the exception's text"
    assert app.page.http.get("/api/config").status_code == 200, "the server carries on"
