"""Open a stored tool, press Save, change nothing — get the same tool back.

`test_a_preset_survives_open_and_save_unchanged` in `test_tool_presets.py`
makes this promise for the preset catalogue, and the presets happen to use only
the fields the form knows about. That is what hid the hole: a `service` or
`script` action carrying a `timeout` lost it on the way through the form,
because `tool_subentry_schema` never declared the field, `tool_form_defaults`
never read it back out and `compose_tool_action` never wrote it. Opening the
card and pressing Save with nothing touched silently reset the budget to the
default.

So this file does not test one field. It pins the whole loop, per action type,
with every field of that type set to something that is *not* its default —
because the only way a lost field shows up is when the value it was carrying
differs from the value the composer would invent.

The path mirrors `ws_tool_save` exactly (serve redacted, merge secrets back,
validate through the served schema, compose): a round trip that skipped the
schema would not have caught this bug either, since the schema is where the
field is declared.
"""

from typing import Any

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.config_flow import (
    TOOL_DEFAULT_ACTION_TYPE,
    TOOL_PARAMS_MODE_SIMPLE,
    build_tool_subentry_data,
    merge_tool_secrets,
    tool_form_defaults,
    tool_subentry_schema,
)
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_TOOL,
    UNIQUE_ID_OPENAI,
)
from custom_components.smartchain.storable import ensure_storable

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

PARAMETERS = {
    "type": "object",
    "properties": {"city": {"type": "string", "description": "Which city"}},
    "required": ["city"],
}

# Every field of every action type, each set away from what the composer would
# fall back to. `timeout` is the one that was being dropped; the rest are here
# so that the next field added to an action cannot be dropped quietly either.
FULL_ACTIONS: dict[str, dict[str, Any]] = {
    "service": {
        "type": "service",
        "domain": "light",
        "service": "turn_on",
        # A list, not the bare string a human would write: see
        # `test_a_bare_entity_id_target_comes_back_as_a_list` below.
        "target": {"entity_id": ["light.porch"]},
        "data": {"brightness_pct": 42},
        "response": True,
        "timeout": 123,
    },
    "template": {
        "type": "template",
        "value_template": "{{ states('sensor.x') }}",
    },
    "rest": {
        "type": "rest",
        "method": "POST",
        "url": "https://example.invalid/x",
        "headers": {"Authorization": "Bearer sekrit"},
        "payload": {"a": 1},
        "timeout": 45,
        "response_format": "json",
    },
    "script": {
        "type": "script",
        "script": "script.morning_routine",
        "variables": {"who": "alice"},
        "timeout": 300,
    },
}


def _entry(hass: HomeAssistant, action: dict[str, Any]) -> tuple[MockConfigEntry, str]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        options={},
        unique_id=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={
                    "description": "Look it up.",
                    "parameters": PARAMETERS,
                    "action": action,
                    "enabled": True,
                    "params_mode": "simple",
                },
                subentry_type=SUBENTRY_TYPE_TOOL,
                title="lookup",
                unique_id=None,
            )
        ],
        minor_version=2,
    )
    entry.add_to_hass(hass)
    return entry, next(iter(entry.subentries))


def _open_and_save(hass: HomeAssistant, entry, subentry_id: str) -> dict[str, Any]:
    """The `ws_tool_schema` -> untouched form -> `ws_tool_save` path."""
    subentry = entry.subentries[subentry_id]

    stored = tool_form_defaults(subentry)  # what the panel is served
    raw = tool_form_defaults(subentry, redact=False)  # what the save path merges against

    schema = tool_subentry_schema(hass, stored)
    declared = {str(key.schema) for key in schema.schema}
    served = {name: value for name, value in stored.items() if name in declared}

    shape = {
        **raw,
        "action_type": served.get("action_type") or TOOL_DEFAULT_ACTION_TYPE,
        "params_mode": served.get("params_mode") or TOOL_PARAMS_MODE_SIMPLE,
    }
    form = ensure_storable(tool_subentry_schema(hass, shape)(served))
    form = merge_tool_secrets(form, raw)

    data, error = build_tool_subentry_data(hass, form, subentry_id=subentry_id)
    assert error is None, error
    return data


@pytest.mark.parametrize("action_type", sorted(FULL_ACTIONS))
async def test_a_fully_populated_action_survives_open_and_save(
    hass: HomeAssistant, action_type: str
) -> None:
    """Nothing set in storage may be different after an untouched Save."""
    action = FULL_ACTIONS[action_type]
    entry, subentry_id = _entry(hass, action)

    data = _open_and_save(hass, entry, subentry_id)

    assert data["action"] == action
    assert data["description"] == "Look it up."
    assert data["parameters"] == PARAMETERS
    assert data["enabled"] is True
    assert data["params_mode"] == "simple"


async def test_a_bare_entity_id_target_comes_back_as_a_list(hass: HomeAssistant) -> None:
    """The one rewrite this loop does make, pinned so it cannot grow.

    `selector.TargetSelector` normalises `entity_id: light.porch` to
    `entity_id: [light.porch]`, so a hand-written tool does not come back
    byte-identical. It is left alone rather than undone: the two forms are the
    same call to `hass.services.async_call`, and unpicking the selector's
    normalisation would put the templated `"{{ entity }}"` targets the presets
    depend on back at risk. Pinned here so that if the normalisation ever
    starts changing something that is *not* neutral, this test says so.
    """
    action = {**FULL_ACTIONS["service"], "target": {"entity_id": "light.porch"}}
    entry, subentry_id = _entry(hass, action)

    data = _open_and_save(hass, entry, subentry_id)

    assert data["action"]["target"] == {"entity_id": ["light.porch"]}
    assert {k: v for k, v in data["action"].items() if k != "target"} == {
        k: v for k, v in action.items() if k != "target"
    }


@pytest.mark.parametrize("action_type", ["service", "script"])
async def test_an_action_without_a_timeout_does_not_gain_one(
    hass: HomeAssistant, action_type: str
) -> None:
    """The other half: absent must stay absent.

    `tools/schema.py` leaves `timeout` without a `default=` on purpose, so that
    a preset or a hand-written tool that never mentioned a budget comes back
    byte-identical. Declaring the form field must not undo that — a `timeout:
    30` appearing in a subentry nobody set it on is the same class of silent
    rewrite as the one above, in the other direction.
    """
    action = {key: value for key, value in FULL_ACTIONS[action_type].items() if key != "timeout"}
    entry, subentry_id = _entry(hass, action)

    data = _open_and_save(hass, entry, subentry_id)

    assert "timeout" not in data["action"]
    assert data["action"] == action
