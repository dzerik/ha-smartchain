"""Tests for tools.yaml voluptuous schemas."""

import pytest
import voluptuous as vol

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


def test_tools_file_schema_requires_tools_key() -> None:
    """Top-level dict must have `tools` key."""
    with pytest.raises(vol.Invalid):
        TOOLS_FILE_SCHEMA({"functions": []})


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
