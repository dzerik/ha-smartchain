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

import logging
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

# An API id that is in the subentry's storage and in no registry: the
# integration that registered it was removed or disabled, and Home Assistant
# forgot it the moment it was unloaded. The stored id survives, because nothing
# rewrites a subentry when an unrelated integration goes away.
GHOST_API = "ghost_api_from_removed_integration"

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


class _SecondAPI(llm.API):
    """A second registered LLM API, so "the stored one" and "the only one" differ.

    With one API in the registry every prefill assertion is ambiguous: a
    hard-coded `["assist"]` and `options.get(CONF_LLM_HASS_API)` produce the
    same form. Registering a second id makes the two testable apart.
    """

    async def async_get_api_instance(self, llm_context: Any) -> Any:
        raise NotImplementedError


def _register_api(hass: HomeAssistant, api_id: str, name: str) -> None:
    llm.async_register_api(hass, _SecondAPI(hass=hass, id=api_id, name=name))


def _offered_apis(result: dict[str, Any]) -> list[str]:
    """The ids the served picker lets the user choose."""
    fields = voluptuous_serialize.convert(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )
    field = next(item for item in fields if item["name"] == CONF_LLM_HASS_API)
    return [option["value"] for option in field["selector"]["select"]["options"]]


def _announcements(caplog: pytest.LogCaptureFixture, api_id: str) -> list[int]:
    """The levels this integration logged the given API id at."""
    return [
        record.levelno
        for record in caplog.records
        if api_id in record.getMessage() and record.name.startswith("custom_components")
    ]


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

    # Absence of the key, not falsity of the value. `normalize_model_input`
    # promises it *pops* the empty selection, and a `llm_hass_api: []` left in
    # storage would satisfy `not data.get(...)` while being a different stored
    # state — one that outlives every later migration reading this key.
    data = entry.subentries[_subentry_id(entry)].data
    assert CONF_LLM_HASS_API not in data


async def test_prefill_is_the_stored_api_not_the_first_registered_one(hass: HomeAssistant) -> None:
    """The form must show what this agent has, not what the system happens to offer.

    With a single API registered, "prefilled from storage" and "hard-coded
    assist" are indistinguishable. A second registered API separates them: the
    agent stores only the second one, so a prefill that is not read from the
    subentry cannot produce this form.
    """
    _register_api(hass, "house_brain", "House Brain")
    entry = _entry(hass, {**STORED_AGENT, CONF_LLM_HASS_API: ["house_brain"]})

    result = await _open_reconfigure(hass, entry)

    assert set(_offered_apis(result)) == {llm.LLM_API_ASSIST, "house_brain"}
    assert _rendered_form(result)[CONF_LLM_HASS_API] == ["house_brain"]


async def test_prefill_drops_an_api_that_is_no_longer_registered(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A stored id whose integration is gone must not be offered back.

    `llm.async_get_apis` is the whole truth about which APIs exist, so an id
    that is not in it names nothing: selecting it makes
    `chat_log.async_provide_llm_data` raise and the agent answer with an error.
    The picker therefore cannot list it and the prefill cannot suggest it — but
    the removal is announced in the log rather than performed in silence.
    """
    entry = _entry(hass, {**STORED_AGENT, CONF_LLM_HASS_API: [llm.LLM_API_ASSIST, GHOST_API]})

    caplog.clear()
    result = await _open_reconfigure(hass, entry)

    assert GHOST_API not in _offered_apis(result)
    assert _rendered_form(result)[CONF_LLM_HASS_API] == [llm.LLM_API_ASSIST]
    # At WARNING, and asserted as such. Home Assistant's own default level is
    # INFO, so an announcement demoted to DEBUG is not a quieter announcement —
    # it is no announcement at all on every real installation, while this test
    # would go on passing because the test harness captures DEBUG. Discarding a
    # value the user stored is the one thing here that may not be silent.
    assert _announcements(caplog, GHOST_API) == [logging.WARNING]


async def test_saving_the_form_lets_go_of_the_dropped_api(hass: HomeAssistant) -> None:
    """The drop must converge: a save writes the surviving selection only."""
    entry = _entry(hass, {**STORED_AGENT, CONF_LLM_HASS_API: [llm.LLM_API_ASSIST, GHOST_API]})
    result = await _open_reconfigure(hass, entry)

    payload = _rendered_form(result)
    payload[CONF_TEMPERATURE] = 0.2

    result = await _submit(hass, result["flow_id"], payload)
    assert result["type"] is FlowResultType.ABORT

    data = entry.subentries[_subentry_id(entry)].data
    assert data[CONF_LLM_HASS_API] == [llm.LLM_API_ASSIST]


async def test_an_agent_whose_only_api_vanished_saves_without_the_key(
    hass: HomeAssistant,
) -> None:
    """Nothing survives the filter, so the field is empty and the key goes."""
    entry = _entry(hass, {**STORED_AGENT, CONF_LLM_HASS_API: [GHOST_API]})
    result = await _open_reconfigure(hass, entry)

    payload = _rendered_form(result)
    assert payload[CONF_LLM_HASS_API] == []

    result = await _submit(hass, result["flow_id"], payload)
    assert result["type"] is FlowResultType.ABORT

    data = entry.subentries[_subentry_id(entry)].data
    assert CONF_LLM_HASS_API not in data


async def test_an_agent_that_never_had_an_api_gets_no_suggestion(hass: HomeAssistant) -> None:
    """No stored selection is not an empty selection.

    The filter must not invent a value where storage has none — a suggested
    `[]` where there was nothing is the same class of unasked-for write the
    prefill exists to prevent.
    """
    stored = {name: value for name, value in STORED_AGENT.items() if name != CONF_LLM_HASS_API}
    entry = _entry(hass, stored)

    result = await _open_reconfigure(hass, entry)

    assert CONF_LLM_HASS_API not in _rendered_form(result)


async def test_a_bare_string_selection_is_one_id_and_not_six_letters(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """`llm_hass_api` is stored as a plain string by a large share of agents.

    Home Assistant's own conversation integrations wrote it that way for years,
    `tools.inventory._configured_llm_apis` still handles the `str` case
    explicitly, and `tests/test_init.py` has entries carrying `"assist"`. A
    filter that iterates the stored value without checking its type iterates
    the *characters*: `'a'`, `'s'`, `'s'`, … None of them is a registered API
    id, so every one is discarded as a ghost, the form opens with an empty
    picker, and the first save takes the agent's Assist API away — which is
    precisely the loss this prefill was written to prevent, reintroduced by its
    own fix. Nothing was dropped here, so nothing may be announced either.
    """
    entry = _entry(hass, {**STORED_AGENT, CONF_LLM_HASS_API: llm.LLM_API_ASSIST})

    caplog.clear()
    result = await _open_reconfigure(hass, entry)

    assert _rendered_form(result)[CONF_LLM_HASS_API] == [llm.LLM_API_ASSIST]
    assert _announcements(caplog, llm.LLM_API_ASSIST) == []

    payload = _rendered_form(result)
    payload[CONF_TEMPERATURE] = 0.2
    result = await _submit(hass, result["flow_id"], payload)
    assert result["type"] is FlowResultType.ABORT

    data = entry.subentries[_subentry_id(entry)].data
    assert data[CONF_LLM_HASS_API] == [llm.LLM_API_ASSIST]


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
