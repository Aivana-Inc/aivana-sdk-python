"""Settings: refuse unsafe or placeholder values, and never put a value in a message."""

import pytest

from basic_chat.config import BLUEPRINT_NAME_MAX, ConfigError, parse_blueprint_name, read_configuration

from .support import KEY


def test_placeholder_and_missing_keys_are_refused():
    for key in ("", "   ", "YOUR_ACTIVE_KEY", "REPLACE_ME", "ai_live_xxx", "your_key_here"):
        with pytest.raises(ConfigError, match="Set an active"):
            read_configuration({"AIVANA_API_KEY": key})
    with pytest.raises(ConfigError, match="Set an active"):
        read_configuration({})


def test_unsafe_api_addresses_are_refused_without_echoing_them():
    for base in ("not-url", "http://example.com", "https://key:secret@example.com", "https://example.com?key=secret",
                 "https://example.com/#secret", "https://example.com/wrong-path", "ftp://example.com", "https://",
                 "https://example.com:notaport"):
        with pytest.raises(ConfigError, match="AIVANA_API_BASE") as caught:
            read_configuration({"AIVANA_API_KEY": KEY, "AIVANA_API_BASE": base})
        assert "secret" not in str(caught.value)


def test_api_address_is_reduced_to_an_origin():
    read = lambda base: read_configuration({"AIVANA_API_KEY": KEY, "AIVANA_API_BASE": base}).api_base  # noqa: E731
    assert read("https://api.aivana.ai/v1/") == "https://api.aivana.ai"
    assert read("https://api.aivana.ai") == "https://api.aivana.ai"
    assert read("https://api.aivana.ai:443") == "https://api.aivana.ai"
    assert read("https://dev-developers.aivana.ai:8443/v1") == "https://dev-developers.aivana.ai:8443"
    # Plain HTTP is for local tests only.
    assert read("http://127.0.0.1:9000") == "http://127.0.0.1:9000"
    assert read("http://localhost:9000/v1") == "http://localhost:9000"
    assert read("http://[::1]:9000") == "http://[::1]:9000"
    assert read_configuration({"AIVANA_API_KEY": KEY}).api_base is None, "use the SDK's own production default"


def test_ports():
    for port in ("0", "1.2", "65536", "oops", "-1", "²", " 80", "٣٠٠٠"):
        with pytest.raises(ConfigError, match="PORT"):
            read_configuration({"AIVANA_API_KEY": KEY, "PORT": port})
    assert read_configuration({"AIVANA_API_KEY": KEY}).port == 3006
    assert read_configuration({"AIVANA_API_KEY": KEY, "PORT": "8080"}).port == 8080
    assert read_configuration({"AIVANA_API_KEY": KEY, "PORT": ""}).port == 3006, "an empty line in .env is the default"


def test_the_key_never_appears_in_a_repr():
    assert KEY not in repr(read_configuration({"AIVANA_API_KEY": KEY}))


def test_blueprint_name_is_one_short_plain_line():
    assert parse_blueprint_name(None) is None
    assert parse_blueprint_name("") is None
    assert parse_blueprint_name("   ") is None, "blank is the same as unset (an empty line in .env)"
    assert parse_blueprint_name("  Juniper Landscaping Assistant  ") == "Juniper Landscaping Assistant"
    assert len(parse_blueprint_name("a" * BLUEPRINT_NAME_MAX)) == BLUEPRINT_NAME_MAX
    assert parse_blueprint_name("<b>Not markup</b> & more") == "<b>Not markup</b> & more", "kept as text; the page never treats it as HTML"
    assert parse_blueprint_name("Café ☕ 日本語") == "Café ☕ 日本語"
    for bad in ("a" * (BLUEPRINT_NAME_MAX + 1), "two\nlines", "tab\there", "carriage\rreturn", "nul\x00byte",
                "line separator", "para separator", "bell\x07", "del\x7f", "c1\x85control"):
        with pytest.raises(ConfigError, match="AIVANA_BLUEPRINT_NAME"):
            parse_blueprint_name(bad)
    with pytest.raises(ConfigError, match="AIVANA_BLUEPRINT_NAME"):
        read_configuration({"AIVANA_API_KEY": KEY, "AIVANA_BLUEPRINT_NAME": "two\nlines"})
    assert read_configuration({"AIVANA_API_KEY": KEY, "AIVANA_BLUEPRINT_NAME": " Support Assistant "}).blueprint_name == "Support Assistant"
    assert read_configuration({"AIVANA_API_KEY": KEY}).blueprint_name is None
