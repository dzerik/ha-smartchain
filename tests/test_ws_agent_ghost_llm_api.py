"""The panel must offer the same LLM APIs the Home Assistant dialog offers.

`config_flow.subentry_schema` filters the stored `llm_hass_api` against
`llm.async_get_apis` before suggesting it, so a dialog never proposes an id
whose integration is gone. The panel does not read that suggestion: it reads
`result.data`, which `ws_agent_schema` builds from the raw `subentry.data`.
So the same agent, opened on the other front, was still offered the ghost —
and because the select's options *are* filtered, submitting the form the panel
had just rendered failed voluptuous validation and came back as `invalid_data`
on a field the user had never touched.

Two fronts, one rule. These tests drive the websocket commands the panel calls,
because that is the front that was broken; the dialog side is covered in
`test_agent_reconfigure_prefill.py`.
"""

import logging
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.helpers import llm
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
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

# Stored in the subentry, registered by nothing: the integration that owned it
# was removed while Home Assistant was running or between two restarts.
GHOST_API = "ghost_api_from_removed_integration"


async def _entry_with_agent(hass, stored_apis):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sekrit-key"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={
                    CONF_CHAT_MODEL: "gpt-4.1-mini",
                    CONF_PROMPT: "carefully tuned",
                    CONF_LLM_HASS_API: stored_apis,
                },
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
    subentry_id = next(iter(entry.subentries))
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ):
        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/schema",
                "entry_id": entry.entry_id,
                "subentry_id": subentry_id,
            }
        )
        msg = await client.receive_json()
    assert msg["success"], msg
    return msg["result"]


def _offered_apis(result):
    field = next(item for item in result["schema"] if item["name"] == CONF_LLM_HASS_API)
    return [option["value"] for option in field["selector"]["select"]["options"]]


async def _save(client, entry, data):
    """Send a form back exactly as `<sc-config-form>` does."""
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
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


async def test_panel_is_not_offered_an_api_that_no_integration_registers(hass, hass_ws_client):
    """The values the panel prefills with must exclude the ghost, exactly as
    the options do — a value the picker cannot render is a value the user
    cannot see, keep or remove."""
    entry = await _entry_with_agent(hass, [llm.LLM_API_ASSIST, GHOST_API])
    client = await hass_ws_client(hass)

    result = await _schema(client, entry)

    assert GHOST_API not in _offered_apis(result)
    assert result["data"][CONF_LLM_HASS_API] == [llm.LLM_API_ASSIST]


async def test_panel_can_save_the_form_it_was_served(hass, hass_ws_client):
    """The reproducer. The panel sends back what it was served; a served value
    the schema rejects makes every later save of this agent fail with
    `invalid_data` on a field nobody edited."""
    entry = await _entry_with_agent(hass, [llm.LLM_API_ASSIST, GHOST_API])
    client = await hass_ws_client(hass)

    result = await _schema(client, entry)
    msg = await _save(client, entry, {**result["data"], CONF_PROMPT: "an unrelated edit"})

    assert msg["success"], msg.get("error")
    data = entry.subentries[next(iter(entry.subentries))].data
    assert data[CONF_LLM_HASS_API] == [llm.LLM_API_ASSIST]
    assert data[CONF_PROMPT] == "an unrelated edit"


async def test_panel_form_of_an_agent_whose_only_api_vanished_is_empty(hass, hass_ws_client):
    """Nothing survives the filter, so the panel shows an empty picker and a
    save writes the agent without the key — the same convergence the dialog
    reaches."""
    entry = await _entry_with_agent(hass, [GHOST_API])
    client = await hass_ws_client(hass)

    result = await _schema(client, entry)
    assert result["data"][CONF_LLM_HASS_API] == []

    msg = await _save(client, entry, result["data"])

    assert msg["success"], msg.get("error")
    assert CONF_LLM_HASS_API not in entry.subentries[next(iter(entry.subentries))].data


async def test_panel_keeps_a_live_api_untouched(hass, hass_ws_client):
    """The filter must not be a blanket drop: a registered id is served back
    unchanged, so opening the panel does not quietly disarm a working agent."""
    entry = await _entry_with_agent(hass, [llm.LLM_API_ASSIST])
    client = await hass_ws_client(hass)

    result = await _schema(client, entry)

    assert result["data"][CONF_LLM_HASS_API] == [llm.LLM_API_ASSIST]


async def test_panel_path_announces_the_drop_at_warning(
    hass, hass_ws_client, caplog: pytest.LogCaptureFixture
):
    """Discarding a value the user stored is not allowed to be silent.

    A stored selection is being rewritten by machinery the user did not ask
    for, so the log line is the only trace they get. The Home Assistant default
    log level is INFO, so the assertion is on the *level* and not merely on the
    text: at DEBUG this announcement does not exist on a real installation, and
    the promise in `_live_llm_apis`' docstring is void.

    Exactly one line, too. Opening one form is one event, and the obvious way
    to make the panel agree with the dialog — calling the filter a second time
    over here — would say it twice for it.
    """
    entry = await _entry_with_agent(hass, [llm.LLM_API_ASSIST, GHOST_API])
    client = await hass_ws_client(hass)

    caplog.clear()
    await _schema(client, entry)

    announcements = [
        record.levelno
        for record in caplog.records
        if GHOST_API in record.getMessage() and record.name.startswith("custom_components")
    ]
    assert announcements == [logging.WARNING]
