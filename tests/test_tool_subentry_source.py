"""A tool from a subentry and a tool from tools.yaml are the same tool.

The whole point of the constructor is that it produces the object the file
already produced, so the dispatcher, the registry, `allowed_tools` and the MCP
naming rules need no idea where a tool came from. The assertions here are
therefore mostly equality between two `CustomTool` instances built from the two
sources, plus the one thing only the merge can decide: what happens when both
sources name the same tool.
"""

from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigSubentry

from custom_components.smartchain.const import SUBENTRY_TYPE_TOOL
from custom_components.smartchain.tools.loader import load_tools_file
from custom_components.smartchain.tools.model import CustomTool, TemplateAction
from custom_components.smartchain.tools.subentry_source import (
    SOURCE_SUBENTRY,
    SOURCE_YAML,
    merge_tool_sources,
    tool_from_subentry,
    tools_from_subentries,
)


def _subentry(title: str, data: dict) -> ConfigSubentry:
    return ConfigSubentry(data=data, subentry_type=SUBENTRY_TYPE_TOOL, title=title, unique_id=None)


PARAMETERS = {
    "type": "object",
    "properties": {"city": {"type": "string", "description": "Which city"}},
    "required": ["city"],
}


@pytest.mark.parametrize(
    "yaml_action,subentry_action",
    [
        (
            "{ type: service, domain: light, service: turn_on, "
            "target: { entity_id: light.porch }, response: true }",
            {
                "type": "service",
                "domain": "light",
                "service": "turn_on",
                "target": {"entity_id": "light.porch"},
                "data": {},
                "response": True,
            },
        ),
        (
            '{ type: template, value_template: "{{ city }}" }',
            {"type": "template", "value_template": "{{ city }}"},
        ),
        (
            "{ type: rest, method: POST, url: https://example.invalid/x, "
            "response_format: json, timeout: 42 }",
            {
                "type": "rest",
                "method": "POST",
                "url": "https://example.invalid/x",
                "headers": {},
                "payload": None,
                "timeout": 42,
                "response_format": "json",
            },
        ),
        (
            "{ type: script, script: script.goodnight, variables: { a: 1 } }",
            {
                "type": "script",
                "script": "script.goodnight",
                "variables": {"a": 1},
            },
        ),
    ],
    ids=["service", "template", "rest", "script"],
)
def test_a_subentry_tool_equals_the_yaml_tool_for_every_action_type(
    tmp_path: Path, yaml_action: str, subentry_action: dict
) -> None:
    """One assertion pinning both sources to one dataclass, per action type.

    If these ever stop comparing equal, something downstream will behave
    differently depending on where the user happened to write the tool — which
    is exactly the failure this design exists to make impossible.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: lookup_weather\n"
        "    description: Look up the weather.\n"
        "    parameters:\n"
        "      type: object\n"
        "      properties:\n"
        "        city:\n"
        "          type: string\n"
        "          description: Which city\n"
        "      required: [city]\n"
        f"    action: {yaml_action}\n"
    )
    (from_yaml,) = load_tools_file(target).yaml_tools

    from_subentry = tool_from_subentry(
        _subentry(
            "lookup_weather",
            {
                "description": "Look up the weather.",
                "parameters": PARAMETERS,
                "action": subentry_action,
                "enabled": True,
            },
        )
    )

    assert from_subentry == from_yaml


def test_a_disabled_subentry_tool_does_not_reach_the_registry() -> None:
    """Same rule the loader applies: a disabled tool does not exist this run."""
    hass = _hass_with(
        _subentry("live_one", _template_data()),
        _subentry("off_one", {**_template_data(), "enabled": False}),
    )

    assert [tool.name for tool in tools_from_subentries(hass)] == ["live_one"]


def test_a_disabled_tool_does_not_reserve_its_name() -> None:
    """`loader.py` documents this for YAML; the subentry path must match.

    Switching a tool off and adding its replacement under the same name must
    keep the replacement — if the disabled one claimed the name first, the
    replacement would be dropped as a duplicate and nothing would work.
    """
    hass = _hass_with(
        _subentry("weather", {**_template_data(), "enabled": False}),
        _subentry("weather", _template_data()),
    )

    tools = tools_from_subentries(hass)
    assert [tool.name for tool in tools] == ["weather"]
    assert tools[0].enabled is True


def test_two_subentries_with_one_name_keep_the_first_and_log(caplog) -> None:
    hass = _hass_with(
        _subentry("weather", {**_template_data(), "description": "first"}),
        _subentry("weather", {**_template_data(), "description": "second"}),
    )

    tools = tools_from_subentries(hass)
    assert [tool.description for tool in tools] == ["first"]
    assert "both named" in caplog.text


def test_a_broken_subentry_is_skipped_rather_than_killing_the_rebuild(caplog) -> None:
    """One unreadable tool must not cost every other tool and the memory
    subsystem behind it — `_reload_registry` builds them in one pass."""
    hass = _hass_with(
        _subentry("broken", {"description": "x", "action": {"type": "nonsense"}}),
        _subentry("fine", _template_data()),
    )

    assert [tool.name for tool in tools_from_subentries(hass)] == ["fine"]
    assert "could not be loaded" in caplog.text


def test_the_subentry_wins_a_name_collision_and_the_shadowing_is_reported(caplog) -> None:
    yaml_tool = CustomTool(
        name="weather",
        description="from the file",
        parameters={"type": "object", "properties": {}},
        action=TemplateAction(value_template="yaml"),
    )
    subentry_tool = CustomTool(
        name="weather",
        description="from the form",
        parameters={"type": "object", "properties": {}},
        action=TemplateAction(value_template="subentry"),
    )
    other = CustomTool(
        name="other",
        description="only in the file",
        parameters={"type": "object", "properties": {}},
        action=TemplateAction(value_template="yaml"),
    )

    tools, sources, shadowed = merge_tool_sources([yaml_tool, other], [subentry_tool])

    assert [tool.description for tool in tools if tool.name == "weather"] == ["from the form"]
    assert shadowed == ["weather"]
    assert sources == {"other": SOURCE_YAML, "weather": SOURCE_SUBENTRY}
    assert "tools.yaml" in caplog.text


def _template_data() -> dict:
    return {
        "description": "does a thing",
        "parameters": {"type": "object", "properties": {}},
        "action": {"type": "template", "value_template": "x"},
        "enabled": True,
    }


class _MockEntry:
    """The two attributes `tool_subentries` reads, and nothing else."""

    def __init__(self, subentries: tuple[ConfigSubentry, ...]) -> None:
        self.subentries = {str(i): sub for i, sub in enumerate(subentries)}
        self.entry_id = "entry"


def _hass_with(*subentries: ConfigSubentry):
    """A stand-in for `hass` exposing only `config_entries.async_entries`.

    Deliberately not the real `hass` fixture with its `async_entries` replaced:
    monkeypatching a bound method on the live ConfigEntries object breaks
    Home Assistant's own teardown, which calls it with a keyword argument.
    `tool_subentries` reads nothing else, so a stub is both sufficient and
    honest about what is under test.
    """

    class _Hass:
        class config_entries:
            @staticmethod
            def async_entries(domain=None):
                return [_MockEntry(subentries)]

    return _Hass()
