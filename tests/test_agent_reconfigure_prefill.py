"""Reopening an agent's form and saving it must change only what was edited.

A config-flow form is a full-replacement form: every field the schema declares
comes back in `user_input`, and `_validate_and_update` writes that dict over the
subentry, preserving only the keys the schema does *not* declare. So a declared
field whose form arrives empty is not "left alone" — it is erased.

What decides whether a field arrives filled is `description={"suggested_value":
...}`. The frontend prefills from it (`computeInitialHaFormData`), falling back
to `default`, and renders nothing when neither is there. `llm_hass_api` had
neither: it is `vol.Optional(CONF_LLM_HASS_API)` with a selector and no default,
so opening an agent to nudge its temperature dropped the selected Assist API —
and `conversation._async_handle_message` then takes the `use_builtin and not
llm_hass_api` branch and hands the sentence to Home Assistant's own agent.

These tests therefore drive the real reconfigure flow and submit what the
*frontend* would submit, computed from the served schema rather than
hand-written: a hand-written payload can only ever restate the bug or the fix.
The third test is the one that matters — it walks the schema, so the next field
added without a suggested value is caught before a user finds it.
"""

from typing import Any
from unittest.mock import patch

import pytest
import voluptuous_serialize
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_ALLOWED_TOOLS,
    CONF_API_KEY,
    CONF_CHAT_HISTORY,
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_DYNAMIC_CONTEXT_ON_ASSIST,
    CONF_DYNAMIC_CONTEXT_PRESET,
    CONF_DYNAMIC_ENTITY_CONTEXT,
    CONF_ENGINE,
    CONF_LLM_HASS_API,
    CONF_MAX_TOKENS,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    DOMAIN,
    ENTITY_TOOL_NAME,
    HISTORY_TOOL_NAME,
    ID_OPENAI,
    MEMORY_TOOL_NAME,
    SUBENTRY_TYPE_CONVERSATION,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

MODELS = ["gpt-4.1-mini", "gpt-4o"]

# One non-default value for every field `subentry_schema` declares, so that a
# field silently reset to its default is a visible difference rather than a
# coincidence. `test_reconfigure_touches_only_the_edited_field` asserts the
# coverage of this dict against the schema itself.
STORED_AGENT = {
    CONF_CHAT_MODEL: "gpt-4.1-mini",
    CONF_CHAT_MODEL_USER: "gpt-4.1-mini",
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: "You are the house.",
    CONF_TEMPERATURE: 0.1,
    CONF_MAX_TOKENS: 1234,
    CONF_PROCESS_BUILTIN_SENTENCES: False,
    CONF_CHAT_HISTORY: False,
    CONF_DYNAMIC_ENTITY_CONTEXT: False,
    CONF_DYNAMIC_CONTEXT_PRESET: "maximal",
    CONF_DYNAMIC_CONTEXT_ON_ASSIST: True,
    CONF_ALLOWED_TOOLS: [HISTORY_TOOL_NAME, MEMORY_TOOL_NAME, ENTITY_TOOL_NAME],
}


def _entry(hass: HomeAssistant, data: dict[str, Any]) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sekrit-key"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data=dict(data),
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            )
        ],
        minor_version=4,
    )
    entry.add_to_hass(hass)
    return entry


def _subentry_id(entry: MockConfigEntry) -> str:
    return next(iter(entry.subentries))


def _rendered_form(result: dict[str, Any]) -> dict[str, Any]:
    """The values the frontend would show in the served form, per field.

    Serialised exactly as `FlowManagerResourceView` serialises it for the
    browser, then read the way `computeInitialHaFormData` reads it: the
    suggested value wins, `default` is the fallback, and a field with neither
    renders blank and is submitted with no value at all.
    """
    fields = voluptuous_serialize.convert(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )
    shown: dict[str, Any] = {}
    for field in fields:
        suggested = (field.get("description") or {}).get("suggested_value")
        if suggested is not None:
            shown[field["name"]] = suggested
        elif "default" in field:
            shown[field["name"]] = field["default"]
    return shown


async def _open_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    with patch(
        "custom_components.smartchain.config_flow.async_fetch_models",
        return_value=list(MODELS),
    ):
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
            context={"source": "reconfigure", "subentry_id": _subentry_id(entry)},
        )
    assert result["type"] is FlowResultType.FORM
    return result


async def _submit(hass: HomeAssistant, flow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with patch(
        "custom_components.smartchain.config_flow.async_fetch_models",
        return_value=list(MODELS),
    ):
        return await hass.config_entries.subentries.async_configure(flow_id, payload)


async def test_editing_only_the_temperature_keeps_the_assist_api(hass: HomeAssistant) -> None:
    """The user drags temperature 0.1 -> 0.2 and saves; the agent must still
    control the house afterwards."""
    entry = _entry(hass, STORED_AGENT)
    result = await _open_reconfigure(hass, entry)

    payload = _rendered_form(result)
    payload[CONF_TEMPERATURE] = 0.2

    result = await _submit(hass, result["flow_id"], payload)
    assert result["type"] is FlowResultType.ABORT

    data = entry.subentries[_subentry_id(entry)].data
    assert data[CONF_TEMPERATURE] == 0.2
    assert data.get(CONF_LLM_HASS_API) == [llm.LLM_API_ASSIST]


async def test_clearing_the_assist_api_still_clears_it(hass: HomeAssistant) -> None:
    """The prefill must not make the field unclearable: a user who removes the
    last chip and saves is asking for no LLM API, and `normalize_model_input`
    drops the empty selection so `conversation` sees no key at all."""
    entry = _entry(hass, STORED_AGENT)
    result = await _open_reconfigure(hass, entry)

    payload = _rendered_form(result)
    payload[CONF_LLM_HASS_API] = []

    result = await _submit(hass, result["flow_id"], payload)
    assert result["type"] is FlowResultType.ABORT

    data = entry.subentries[_subentry_id(entry)].data
    assert not data.get(CONF_LLM_HASS_API)


async def test_reconfigure_touches_only_the_edited_field(hass: HomeAssistant) -> None:
    """Every declared field, not one named field.

    `_validate_and_update` writes `user_input` over the subentry, so any field
    the served form fails to prefill is destroyed by a save that never touched
    it. Walking the schema means the guarantee covers fields added later, which
    is the whole point — `llm_hass_api` was the second field in this schema to
    be read back by the runtime and the first to be lost.
    """
    entry = _entry(hass, STORED_AGENT)
    result = await _open_reconfigure(hass, entry)

    declared = {str(key.schema) for key in result["data_schema"].schema}
    assert declared <= set(STORED_AGENT), (
        f"schema fields with no stored value in this test: {sorted(declared - set(STORED_AGENT))}"
    )

    payload = _rendered_form(result)
    payload[CONF_TEMPERATURE] = 0.2

    result = await _submit(hass, result["flow_id"], payload)
    assert result["type"] is FlowResultType.ABORT

    data = entry.subentries[_subentry_id(entry)].data
    untouched = sorted(declared - {CONF_TEMPERATURE})
    lost = {
        name: (STORED_AGENT[name], data.get(name, "<absent>"))
        for name in untouched
        if data.get(name, "<absent>") != STORED_AGENT[name]
    }
    assert not lost, f"fields changed by a save that never touched them: {lost}"
