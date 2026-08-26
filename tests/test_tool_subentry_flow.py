"""The tool subentry type in Home Assistant's own dialog.

The panel is not the only way in: Devices & Services can add a subentry too,
and a tool created there must be the same tool, held to the same rules. That is
what `build_tool_subentry_data` and one schema builder are for — this file is
where the flow half of that claim is exercised, plus the two claims that only
make sense against the whole form: that it is served rather than declared, and
that every field it can render carries translated text in both locales.
"""

import json
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.config_flow import (
    ConfigFlow,
    tool_form_defaults,
    tool_subentry_schema,
)
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_OPENAI,
    SUBENTRY_TYPE_TOOL,
    TOOL_ACTION_TYPES,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE = Path(__file__).parent.parent / "custom_components" / "smartchain"


def _entry(hass: HomeAssistant, *, engine=ID_OPENAI, subentries=()) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: engine, CONF_API_KEY: "k"},
        options={},
        unique_id=UNIQUE_ID_OPENAI,
        subentries_data=list(subentries),
        minor_version=2,
    )
    entry.add_to_hass(hass)
    return entry


# --- the type is offered --------------------------------------------------


@pytest.mark.parametrize("engine", [ID_OPENAI, ID_DEEPSEEK, ID_ANTHROPIC])
async def test_every_provider_offers_the_tool_type(hass: HomeAssistant, engine) -> None:
    """A custom tool belongs to the installation, not to one provider: the tool
    registry is global and every agent draws from it, so gating this on a
    provider capability would be arbitrary."""
    entry = _entry(hass, engine=engine)
    assert SUBENTRY_TYPE_TOOL in ConfigFlow.async_get_supported_subentry_types(entry)


# --- the two-step flow ----------------------------------------------------


async def test_flow_creates_a_tool(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TOOL), context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "kitchen_temperature",
            "description": "Read the kitchen temperature.",
            "enabled": True,
            "action_type": "template",
            "params_mode": "simple",
        },
    )
    assert result["type"] == "form"
    assert result["step_id"] == "details"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"params_rows": [], "value_template": "{{ states('sensor.kitchen') }}"},
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "kitchen_temperature"
    # The title *is* the name, the convention every subentry type here follows.
    assert "name" not in result["data"]
    assert result["data"]["action"] == {
        "type": "template",
        "value_template": "{{ states('sensor.kitchen') }}",
    }
    assert result["data"]["parameters"] == {"type": "object", "properties": {}}


@pytest.mark.parametrize(
    "action_type,expected",
    [
        ("service", {"service", "target", "service_data", "response"}),
        ("template", {"value_template"}),
        ("rest", {"method", "url", "headers", "payload", "timeout", "response_format"}),
        ("script", {"script", "variables"}),
    ],
)
async def test_the_second_step_follows_the_first_answer(
    hass: HomeAssistant, action_type, expected
) -> None:
    """A config-flow form cannot change shape while open, so the questions that
    decide the shape are asked first and the rest follow. This is the flow
    equivalent of the panel's `reactive` round trip, from the same builder."""
    entry = _entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TOOL), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "x_tool",
            "description": "does something",
            "enabled": True,
            "action_type": action_type,
            "params_mode": "simple",
        },
    )
    fields = {str(key.schema) for key in result["data_schema"].schema}
    assert expected <= fields
    # The basics are not asked twice.
    assert not fields & {"name", "description", "enabled", "action_type", "params_mode"}


async def test_the_flow_refuses_a_name_the_panel_would_refuse(hass: HomeAssistant) -> None:
    """One validator, two front doors."""
    entry = _entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TOOL), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "search_memory",
            "description": "shadow a built-in",
            "enabled": True,
            "action_type": "template",
            "params_mode": "simple",
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"params_rows": [], "value_template": "x"}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "reserved_name"}


async def test_reconfigure_round_trips_a_stored_tool(hass: HomeAssistant) -> None:
    entry = _entry(
        hass,
        subentries=[
            ConfigSubentryData(
                data={
                    "description": "Look it up.",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                    "action": {
                        "type": "rest",
                        "method": "POST",
                        "url": "https://example.invalid/x",
                        "headers": {},
                        "payload": None,
                        "timeout": 20,
                        "response_format": "json",
                    },
                    "enabled": True,
                    "params_mode": "simple",
                },
                subentry_type=SUBENTRY_TYPE_TOOL,
                title="lookup",
                unique_id=None,
            )
        ],
    )
    subentry_id = next(iter(entry.subentries))

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TOOL),
        context={"source": "reconfigure", "subentry_id": subentry_id},
    )
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "lookup",
            "description": "Look it up, better.",
            "enabled": True,
            "action_type": "rest",
            "params_mode": "simple",
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "params_rows": [{"name": "city", "type": "string", "required": True}],
            "method": "POST",
            "url": "https://example.invalid/x",
            "headers": {},
            "payload": {},
            "timeout": 20,
            "response_format": "json",
        },
    )
    assert result["type"] == "abort"

    stored = entry.subentries[subentry_id]
    assert stored.data["description"] == "Look it up, better."
    assert stored.data["parameters"]["required"] == ["city"]
    assert stored.data["action"]["timeout"] == 20


# --- form defaults --------------------------------------------------------


def test_form_defaults_reverse_the_composition() -> None:
    """`tool_form_defaults` is the inverse of `build_tool_subentry_data`; if it
    drifts, editing a tool silently rewrites it."""

    class _Sub:
        title = "porch"
        data = {
            "description": "Turn it on.",
            "parameters": {
                "type": "object",
                "properties": {"delay": {"type": "integer", "description": "Seconds"}},
            },
            "action": {
                "type": "service",
                "domain": "light",
                "service": "turn_on",
                "target": {"entity_id": ["light.porch"]},
                "data": {"brightness": 200},
                "response": False,
            },
            "enabled": True,
            "params_mode": "simple",
        }

    defaults = tool_form_defaults(_Sub())
    assert defaults["name"] == "porch"
    assert defaults["service"] == "light.turn_on"
    assert defaults["service_data"] == {"brightness": 200}
    assert defaults["params_rows"] == [
        {"name": "delay", "type": "integer", "description": "Seconds", "required": False}
    ]


# --- translations ---------------------------------------------------------


@pytest.mark.parametrize("locale", ["en", "ru"])
def test_every_renderable_tool_field_has_a_label_and_a_description(hass, locale) -> None:
    """Schema-driven, not a hand-written field list — a field added behind an
    `if action_type == ...` renders silently with no error and no log line, and
    only walking every branch of the builder catches it.
    """
    doc = json.loads((BASE / "translations" / f"{locale}.json").read_text(encoding="utf-8"))
    tool = doc["config_subentries"]["tool"]["step"]

    known: set[str] = set()
    for step in tool.values():
        known |= set(step.get("data", {}))

    described: set[str] = set()
    for step in tool.values():
        described |= {
            key for key, value in step.get("data_description", {}).items() if value.strip()
        }

    renderable: set[str] = set()
    for action_type in TOOL_ACTION_TYPES:
        for params_mode in ("simple", "advanced"):
            schema = tool_subentry_schema(
                hass, {"action_type": action_type, "params_mode": params_mode}
            )
            renderable |= {str(key.schema) for key in schema.schema}

    assert not renderable - known, f"fields with no label in {locale}"
    assert not renderable - described, f"fields with no description in {locale}"


# --- the panel declares nothing -------------------------------------------


def test_the_panel_names_no_field_of_the_tool_form(hass) -> None:
    """The requirement is that the backend serialises the schema and
    <sc-config-form> renders it — so the Tools tab must not know a field name.

    Checked against the fields that exist *only* on the form. `name`,
    `description`, `action_type` and `enabled` are deliberately excluded: they
    also come back from `smartchain/tool/list` as list columns, which the tab
    legitimately reads, so their presence proves nothing either way. Everything
    else appearing in that file would mean the constructor had leaked into
    JavaScript.
    """
    source = (BASE / "panel" / "components" / "tools-tab.js").read_text(encoding="utf-8")
    # The two documentation constants are excised first. They describe the keys
    # of *tools.yaml*, which is a different vocabulary that happens to overlap:
    # `url` in a YAML example is not the panel declaring the form's `url` field,
    # and the Import/Export box would be useless without that reference.
    import re as _re

    panel = _re.sub(r"const (TOOLS_PLACEHOLDER|TOOLS_HELP_HTML) = `.*?`;", "", source, flags=_re.S)
    assert len(panel) < len(source), "the documentation constants were not found to excise"

    list_columns = {"name", "description", "action_type", "enabled"}
    form_only: set[str] = set()
    for action_type in TOOL_ACTION_TYPES:
        for params_mode in ("simple", "advanced"):
            schema = tool_subentry_schema(
                hass, {"action_type": action_type, "params_mode": params_mode}
            )
            form_only |= {str(key.schema) for key in schema.schema}
    form_only -= list_columns

    # Matched as a quoted string literal, which is how JavaScript would name a
    # form field it knew about — in a payload it builds or a value it reads out
    # of one. A bare word match instead flags `import.meta.url` and the word
    # "target" in an English sentence, neither of which is a field name.
    leaked = sorted(field for field in form_only if f'"{field}"' in panel or f"'{field}'" in panel)
    assert not leaked, f"the Tools tab names form fields it should never know: {leaked}"
