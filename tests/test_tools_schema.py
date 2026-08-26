"""Tests for tools.yaml voluptuous schemas."""

import pytest
import voluptuous as vol

from custom_components.smartchain.tools.model import (
    ACTION_DEFAULT_TIMEOUT,
    ACTION_MAX_TIMEOUT,
    ACTION_MIN_TIMEOUT,
    ScriptAction,
    ServiceAction,
)
from custom_components.smartchain.tools.schema import TOOL_SCHEMA, TOOLS_FILE_SCHEMA


def test_tool_schema_accepts_valid_service_tool() -> None:
    """A correct service-action tool passes validation."""
    raw = {
        "name": "turn_on_light",
        "description": "Turn on a light",
        "parameters": {"type": "object", "properties": {}},
        "action": {
            "type": "service",
            "domain": "light",
            "service": "turn_on",
            "target": {"area_id": "kitchen"},
        },
    }
    TOOL_SCHEMA(raw)


def test_tool_schema_accepts_valid_template_tool() -> None:
    """Template tool passes validation."""
    raw = {
        "name": "ping",
        "description": "say pong",
        "parameters": {"type": "object", "properties": {}},
        "action": {"type": "template", "value_template": "pong"},
    }
    TOOL_SCHEMA(raw)


def test_tool_schema_accepts_valid_rest_tool() -> None:
    """REST tool passes validation."""
    raw = {
        "name": "weather",
        "description": "fetch weather",
        "parameters": {"type": "object", "properties": {}},
        "action": {
            "type": "rest",
            "method": "GET",
            "url": "https://example.com/api",
            "timeout": 5,
            "response_format": "json",
        },
    }
    TOOL_SCHEMA(raw)


def test_tool_schema_accepts_valid_script_tool() -> None:
    """Script tool passes validation."""
    raw = {
        "name": "morning",
        "description": "run morning script",
        "parameters": {"type": "object", "properties": {}},
        "action": {"type": "script", "script": "script.morning_routine"},
    }
    TOOL_SCHEMA(raw)


def test_tool_schema_rejects_bad_name() -> None:
    """Names not matching the LLM-safe regex are rejected."""
    raw = {
        "name": "Turn-On-Light",  # uppercase + dashes
        "description": "x",
        "parameters": {"type": "object", "properties": {}},
        "action": {"type": "template", "value_template": "x"},
    }
    with pytest.raises(vol.Invalid):
        TOOL_SCHEMA(raw)


def test_tool_schema_enabled_defaults_true_when_omitted() -> None:
    """`enabled` is optional; omitting it must not disable the tool."""
    raw = {
        "name": "ping",
        "description": "say pong",
        "parameters": {"type": "object", "properties": {}},
        "action": {"type": "template", "value_template": "pong"},
    }
    validated = TOOL_SCHEMA(raw)
    assert validated["enabled"] is True


def test_tool_schema_accepts_explicit_enabled_false() -> None:
    """`enabled: false` validates and is preserved."""
    raw = {
        "name": "ping",
        "description": "say pong",
        "parameters": {"type": "object", "properties": {}},
        "action": {"type": "template", "value_template": "pong"},
        "enabled": False,
    }
    validated = TOOL_SCHEMA(raw)
    assert validated["enabled"] is False


def test_tool_schema_rejects_unknown_action_type() -> None:
    """Unknown action types are rejected."""
    raw = {
        "name": "x",
        "description": "x",
        "parameters": {"type": "object", "properties": {}},
        "action": {"type": "shell", "cmd": "rm -rf /"},
    }
    with pytest.raises(vol.Invalid):
        TOOL_SCHEMA(raw)


def test_tools_file_schema_accepts_empty_list() -> None:
    """A file with `tools: []` is valid (means: registry is empty)."""
    TOOLS_FILE_SCHEMA({"tools": []})


def test_tools_file_schema_rejects_unknown_top_level_keys() -> None:
    """Unknown top-level keys are rejected (only `tools` and `mcp_servers` allowed)."""
    with pytest.raises(vol.Invalid):
        TOOLS_FILE_SCHEMA({"functions": []})


def test_tools_file_schema_accepts_empty_dict_now() -> None:
    """With both keys Optional, an empty top-level dict is valid (yields empty registry)."""
    result = TOOLS_FILE_SCHEMA({})
    assert result == {"tools": [], "mcp_servers": []}


def test_tool_schema_rejects_parameters_that_are_not_a_json_schema() -> None:
    """`parameters` is held to the JSON Schema metaschema, not just its shell.

    USAGE §7.0.1 promises the schema "is validated before it is saved, and
    again against every call". Before this, only the outer three keys were
    checked: `type: nosuchtype` on a property sailed through the file and the
    form, and blew up inside `jsonschema.validate` at the first call. The
    message names the offending path so the user knows which argument to fix.
    """
    raw = {
        "name": "weather",
        "description": "x",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "nosuchtype"}},
        },
        "action": {"type": "template", "value_template": "x"},
    }
    with pytest.raises(vol.Invalid) as err:
        TOOL_SCHEMA(raw)
    assert "properties.city.type" in str(err.value)


def test_tool_schema_still_accepts_a_schema_the_rows_cannot_express() -> None:
    """The metaschema check must not narrow what `advanced` mode may write."""
    raw = {
        "name": "complex_tool",
        "description": "x",
        "parameters": {
            "type": "object",
            "properties": {
                "when": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                "rooms": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["when"],
        },
        "action": {"type": "template", "value_template": "x"},
    }
    TOOL_SCHEMA(raw)


def test_omitted_timeout_is_not_invented_by_the_validator() -> None:
    """The budget is the dataclass's default, never a key this validator adds.

    `validate_action` is also what the panel's save path runs, and a key it
    invents is a key the form never wrote: opening a preset-installed tool and
    pressing Save with nothing changed would rewrite the stored subentry. The
    default belongs to `ScriptAction`/`ServiceAction`; here the key is only
    validated when the user actually wrote one.
    """
    base = {
        "name": "x",
        "description": "x",
        "parameters": {"type": "object", "properties": {}},
    }
    service = TOOL_SCHEMA(
        {**base, "action": {"type": "service", "domain": "light", "service": "turn_on"}}
    )
    assert "timeout" not in service["action"]

    script = TOOL_SCHEMA({**base, "action": {"type": "script", "script": "script.morning"}})
    assert "timeout" not in script["action"]

    # …and the budget still exists, because the dataclass carries it.
    assert ServiceAction(domain="light", service="turn_on").timeout == ACTION_DEFAULT_TIMEOUT
    assert ScriptAction(script="script.morning").timeout == ACTION_DEFAULT_TIMEOUT


def test_service_action_timeout_is_accepted_and_bounded() -> None:
    """An explicit timeout is kept; one outside the range is refused."""
    base = {
        "name": "x",
        "description": "x",
        "parameters": {"type": "object", "properties": {}},
        "action": {"type": "service", "domain": "light", "service": "turn_on"},
    }
    ok = {**base, "action": {**base["action"], "timeout": 45}}
    assert TOOL_SCHEMA(ok)["action"]["timeout"] == 45

    too_big = {**base, "action": {**base["action"], "timeout": ACTION_MAX_TIMEOUT + 1}}
    with pytest.raises(vol.Invalid):
        TOOL_SCHEMA(too_big)

    too_small = {**base, "action": {**base["action"], "timeout": ACTION_MIN_TIMEOUT - 1}}
    with pytest.raises(vol.Invalid):
        TOOL_SCHEMA(too_small)


def test_script_action_timeout_is_accepted_and_bounded() -> None:
    """Same bounds for `script`."""
    base = {
        "name": "x",
        "description": "x",
        "parameters": {"type": "object", "properties": {}},
        "action": {"type": "script", "script": "script.morning_routine"},
    }
    ok = {**base, "action": {**base["action"], "timeout": 120}}
    assert TOOL_SCHEMA(ok)["action"]["timeout"] == 120

    too_big = {**base, "action": {**base["action"], "timeout": ACTION_MAX_TIMEOUT + 1}}
    with pytest.raises(vol.Invalid):
        TOOL_SCHEMA(too_big)


def test_tool_schema_unknown_action_type_has_clear_message() -> None:
    """Unknown action types produce a 'unknown action type' message."""
    raw = {
        "name": "x",
        "description": "x",
        "parameters": {"type": "object", "properties": {}},
        "action": {"type": "shell", "cmd": "rm -rf /"},
    }
    with pytest.raises(vol.Invalid, match="unknown action type"):
        TOOL_SCHEMA(raw)
