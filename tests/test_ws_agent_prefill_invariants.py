"""What `ws_agent_schema` promises the panel about an agent's values.

`_prefill` is the seam where the config flow's decisions about *values* — not
just about fields — reach the panel. Three of its promises had no test at all,
which a mutation run proved: flipping `if suggested is not None` to always
assign, and flipping `if name not in served: continue` to never skip, both left
every test in the suite green while changing what the panel is served.

These tests state the promises directly, through the websocket command the
panel actually calls, so a change to either one has to argue with a test.
"""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_ALLOWED_TOOLS,
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_LLM_HASS_API,
    CONF_PROMPT,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

MODELS = ["", "gpt-4.1-mini"]


async def _entry_with_agent(hass, stored):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sekrit-key"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data=stored,
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            )
        ],
        minor_version=4,
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    return entry


async def _schema(client, entry):
    """What the panel receives when it opens this agent's form."""
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=MODELS,
    ):
        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/schema",
                "entry_id": entry.entry_id,
                "subentry_id": next(iter(entry.subentries)),
            }
        )
        msg = await client.receive_json()
    assert msg["success"], msg
    return msg["result"]


async def _save(client, entry, data):
    """Send a form back exactly as `<sc-config-form>` does."""
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=MODELS,
    ):
        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/save",
                "entry_id": entry.entry_id,
                "subentry_id": next(iter(entry.subentries)),
                "data": data,
            }
        )
        return await client.receive_json()


def _dialog_suggestions(hass, entry):
    """The `suggested_value` a Home Assistant dialog would render this agent with."""
    from custom_components.smartchain.config_flow import subentry_schema

    subentry = next(iter(entry.subentries.values()))
    schema = subentry_schema(hass, entry.unique_id, dict(subentry.data), models=MODELS)
    return {
        str(key.schema): key.description["suggested_value"]
        for key in schema.schema
        if isinstance(getattr(key, "description", None), dict)
        and "suggested_value" in key.description
    }


async def test_a_suggestion_of_none_is_not_served_as_a_value(hass, hass_ws_client):
    """`None` from the schema means "nothing to offer", not "offer nothing".

    `_live_llm_apis` answers `None` for an agent whose stored selection is
    empty, and a Home Assistant dialog renders that as a blank picker — no
    value at all. Sending the literal `null` to the panel instead hands
    `<ha-form>` a value its multi-select cannot hold, and the panel echoes it
    straight back into a save that voluptuous refuses.
    """
    entry = await _entry_with_agent(
        hass, {CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "p", CONF_LLM_HASS_API: []}
    )
    client = await hass_ws_client(hass)

    result = await _schema(client, entry)

    assert CONF_LLM_HASS_API not in result["data"], result["data"].get(CONF_LLM_HASS_API)


async def test_an_agent_stored_with_an_empty_llm_api_can_still_be_saved(hass, hass_ws_client):
    """The remaining corner of the ghost-API story, in the other direction.

    `llm_hass_api` reaches storage as an empty *string* on agents written
    before the field was a multi-select. The Home Assistant dialog walks out of
    that state without noticing: the suggestion is `None`, the picker opens
    blank, and the save drops the key. The panel was served the raw `""`,
    echoed it back, and every save of that agent died on `invalid_data:
    llm_hass_api` — a field the user could not even see a value in. Two fronts,
    one state, one answer.
    """
    entry = await _entry_with_agent(
        hass, {CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "p", CONF_LLM_HASS_API: ""}
    )
    client = await hass_ws_client(hass)

    result = await _schema(client, entry)
    msg = await _save(client, entry, {**result["data"], CONF_PROMPT: "an unrelated edit"})

    assert msg["success"], msg.get("error")
    assert result["data"].get(CONF_LLM_HASS_API) != ""
    stored = entry.subentries[next(iter(entry.subentries))].data
    assert CONF_LLM_HASS_API not in stored
    assert stored[CONF_PROMPT] == "an unrelated edit"


async def test_the_panel_is_prefilled_with_what_the_dialog_would_render(hass, hass_ws_client):
    """One agent, two fronts, one set of values.

    The panel builds its fields from the serialised schema and takes its values
    from `data`, so every value the schema *decides* rather than merely echoes
    has to travel through `data` or the two forms disagree about the same
    agent. Comparing against `subentry_schema`'s own suggestions keeps that
    written once, in the flow.
    """
    entry = await _entry_with_agent(hass, {CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "tuned"})
    client = await hass_ws_client(hass)

    result = await _schema(client, entry)

    expected = {
        name: value for name, value in _dialog_suggestions(hass, entry).items() if value is not None
    }
    assert result["data"] == expected


async def test_an_agent_with_no_stored_tool_list_is_shown_the_tools_it_has(hass, hass_ws_client):
    """The user-visible half of the same rule.

    An agent that predates v5.4.0 — and every agent the panel itself has
    created, because the panel never sent the field — carries no
    `allowed_tools` at all while still having built-ins switched on.
    `materialise_allowed_tools` is what turns that into the list the form
    shows, and the Home Assistant dialog renders it. The panel, serving only
    keys storage already had, rendered an empty picker instead: a screen that
    says this agent can do nothing, about an agent that can do four things —
    and the first tool the user adds there replaces all four.
    """
    from custom_components.smartchain.tools.inventory import materialise_allowed_tools

    stored = {CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "p"}
    entry = await _entry_with_agent(hass, stored)
    client = await hass_ws_client(hass)

    result = await _schema(client, entry)

    expected = materialise_allowed_tools(stored)
    assert expected, "nothing to prove if the agent really has no tools"
    assert result["data"][CONF_ALLOWED_TOOLS] == expected


async def test_saving_the_served_form_keeps_the_agents_tools(hass, hass_ws_client):
    """And the round trip: what the panel is served must survive being sent back."""
    from custom_components.smartchain.tools.inventory import materialise_allowed_tools

    stored = {CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "p"}
    entry = await _entry_with_agent(hass, stored)
    client = await hass_ws_client(hass)

    result = await _schema(client, entry)
    msg = await _save(client, entry, {**result["data"], CONF_PROMPT: "an unrelated edit"})

    assert msg["success"], msg.get("error")
    saved = entry.subentries[next(iter(entry.subentries))].data
    assert saved[CONF_ALLOWED_TOOLS] == materialise_allowed_tools(stored)
