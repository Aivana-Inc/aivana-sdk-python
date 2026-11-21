"""The Blueprint compiler and loader: strict, never coercing, and never echoing file contents."""

import copy
import json
import os
import stat
import sys

import pytest

from basic_chat.blueprint import BlueprintError, compile_blueprint, load_blueprint, thaw

from .conftest import EXPORTED_BLUEPRINT


def definition(configuration=None, history="session"):
    base = {
        "purpose": "Help users",
        "configuration": {"system": "Be clear", "effort": "auto", "web_search": False, "temperature": 0.7, "top_p": None,
                          "max_tokens": 2048, "stop_sequences": [], "response_format": {"type": "text"}},
        "conversation": {"history": history},
    }
    base["configuration"].update(configuration or {})
    return base


def test_unsupported_features_and_malformed_settings_are_refused_without_coercion():
    invalid = [
        None, [], {}, "text", 7,
        {**definition(), "id": "bp_1"},
        {**definition(), "knowledge": {"source_set_id": "source", "requirement": "required"}},
        {**definition(), "purpose": " "}, {**definition(), "purpose": "x" * 1001}, {**definition(), "purpose": 5},
        definition({"system": "x" * 8001}), definition({"system": None}), definition({"effort": "HIGH"}),
        definition({"web_search": "false"}), definition({"web_search": 0}),
        definition({"temperature": -1}), definition({"temperature": 2.1}),
        definition({"top_p": 1.1, "temperature": None}), definition({"temperature": 0, "top_p": 0}),
        definition({"temperature": float("nan")}), definition({"temperature": float("inf")}), definition({"temperature": "0"}),
        definition({"temperature": True}),  # a bool is not a number, even though Python says it is an int
        definition({"max_tokens": 0}), definition({"max_tokens": 1.5}), definition({"max_tokens": 32001}),
        definition({"max_tokens": True}), definition({"max_tokens": 2.0}),
        definition({"stop_sequences": [""]}), definition({"stop_sequences": [False]}), definition({"stop_sequences": ["END"] * 5}),
        definition({"stop_sequences": "END"}),
        definition({"response_format": {"type": "json_schema", "schema": {"type": "object"}}}),
        definition({"response_format": {"type": "text", "schema": {}}}), definition({"response_format": {"type": "text", "extra": True}}),
        definition({"output_shape": "json"}), definition({}, "forever"),
        {**definition(), "conversation": {"history": "none", "maxTurns": 5}},
        definition({"stop_sequences": ["漢" * 23000]}),  # over 64 KiB once written as UTF-8
    ]
    for value in invalid:
        with pytest.raises(BlueprintError):
            compile_blueprint(value)
    missing = definition()
    del missing["configuration"]["top_p"]
    with pytest.raises(BlueprintError, match="Required fields"):
        compile_blueprint(missing)
    compile_blueprint({**definition({"response_format": {"type": "text", "schema": None}}), "knowledge": None})


def test_the_real_agent_kit_export_compiles_to_the_expected_options():
    compiled = compile_blueprint(EXPORTED_BLUEPRINT)
    assert dict(compiled.options) == {"system": "Be clear", "effort": "auto", "web_search": False, "response_format": {"type": "text"},
                                      "temperature": 0.7, "max_tokens": 2048}
    assert compiled.history == "session" and compiled.purpose == "Help users"


def test_zero_is_a_value_and_null_means_leave_it_out():
    options = compile_blueprint(definition({"temperature": 0, "top_p": None, "max_tokens": 1})).options
    assert options["temperature"] == 0 and options["max_tokens"] == 1 and "top_p" not in options
    options = compile_blueprint(definition({"temperature": None, "top_p": 0, "max_tokens": None})).options
    assert options["top_p"] == 0 and "temperature" not in options and "max_tokens" not in options


def test_compiled_options_are_independent_of_later_changes():
    original = definition({"stop_sequences": ["END"]})
    compiled = compile_blueprint(original)
    original["configuration"]["system"] = "Later"
    original["configuration"]["stop_sequences"].append("STOP")
    assert compiled.options["system"] == "Be clear"
    assert compiled.options["stop_sequences"] == ("END",)
    with pytest.raises(TypeError):
        compiled.options["system"] = "Changed"  # type: ignore[index]
    # What reaches the SDK is a fresh copy each time, so one request can never change the next.
    first = thaw(compiled.options)
    first["stop_sequences"].append("X")
    first["response_format"]["type"] = "json_schema"
    again = thaw(compiled.options)
    assert again["stop_sequences"] == ["END"] and again["response_format"] == {"type": "text"}


def test_the_purpose_is_trimmed_and_only_descriptive():
    compiled = compile_blueprint({**definition(), "purpose": "  Help users  "})
    assert compiled.purpose == "Help users"
    assert "Help users" not in json.dumps(thaw(compiled.options)), "purpose is not an instruction"


def test_conventional_file_is_optional_and_explicit_paths_never_fall_back(tmp_path):
    folder = tmp_path / "blueprint with spaces"
    folder.mkdir()
    assert load_blueprint({}, folder) is None
    with pytest.raises(BlueprintError, match="Cannot open"):
        load_blueprint({"AIVANA_BLUEPRINT_FILE": "missing.json"}, folder)
    path = folder / "blueprint-definition.json"
    path.write_text(json.dumps(definition()), encoding="utf-8")
    assert load_blueprint({}, folder) == definition()
    assert load_blueprint({"AIVANA_BLUEPRINT_FILE": str(path)}, tmp_path / "unrelated") == definition()
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(definition()).encode())  # a byte order mark, as some editors add
    assert load_blueprint({}, folder) == definition()


@pytest.mark.parametrize("contents", [b'{"private_secret":', b"\xff\xfe", b" " * (256 * 1024 + 1), b'{"a": NaN}', b'{"purpose": Infinity}'])
def test_a_bad_file_is_refused_and_its_contents_are_never_in_the_message(tmp_path, contents):
    (tmp_path / "blueprint-definition.json").write_bytes(contents)
    with pytest.raises(BlueprintError) as caught:
        load_blueprint({}, tmp_path)
    assert "private_secret" not in str(caught.value) and "NaN" not in str(caught.value)


def test_a_folder_is_refused(tmp_path):
    (tmp_path / "folder").mkdir()
    with pytest.raises(BlueprintError):
        load_blueprint({"AIVANA_BLUEPRINT_FILE": "folder"}, tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="named pipes are a POSIX feature")
def test_a_named_pipe_cannot_hang_startup(tmp_path):
    pipe = tmp_path / "blueprint-definition.json"
    os.mkfifo(pipe)
    assert stat.S_ISFIFO(pipe.stat().st_mode)
    with pytest.raises(BlueprintError, match="regular"):
        load_blueprint({}, tmp_path)


def test_an_invalid_definition_in_a_valid_file_is_refused(tmp_path):
    bad = copy.deepcopy(definition())
    bad["configuration"]["effort"] = "typo"
    (tmp_path / "blueprint-definition.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(BlueprintError, match="Effort"):
        load_blueprint({}, tmp_path)
