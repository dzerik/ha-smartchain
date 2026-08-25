"""Entry settings over the panel's websocket API."""

from unittest.mock import patch

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_PROMPT,
    DOMAIN,
    ID_OPENAI,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SECRET = "sk-settings-secret"


@pytest.fixture(autouse=True)
def _models():
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini", "gpt-4.1"],
    ):
        yield


@pytest.fixture
async def entry(hass):
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET},
        options={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "current"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
    )
    entry.add_to_hass(hass)
    return entry


async def test_get_returns_the_current_options(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/settings/get", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["data"][CONF_PROMPT] == "current"
    assert msg["result"]["schema"]
    assert msg["result"]["labels"]


async def test_save_writes_to_options_and_never_to_data(hass, hass_ws_client, entry):
    """Settings live in options. Writing them into data would put them where
    the provider credential lives."""
    before = dict(entry.data)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/settings/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1", CONF_PROMPT: "updated"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    assert entry.options[CONF_PROMPT] == "updated"
    assert entry.options[CONF_CHAT_MODEL] == "gpt-4.1"
    assert dict(entry.data) == before


async def test_save_rejects_input_with_no_model(hass, hass_ws_client, entry):
    before = dict(entry.options)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/settings/save",
            "entry_id": entry.entry_id,
            "data": {CONF_PROMPT: "no model"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"], msg
    assert msg["error"]["code"] == "invalid_data"
    assert dict(entry.options) == before


async def test_get_serves_only_declared_fields(hass, hass_ws_client, entry):
    """The trap D1 hit: a served key the schema does not declare makes the form
    permanently unsavable, because save uses PREVENT_EXTRA."""
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "a_field_no_schema_declares": True}
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/settings/get", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert "a_field_no_schema_declares" not in msg["result"]["data"]

    # And what was served must round-trip.
    await client.send_json_auto_id(
        {
            "type": "smartchain/settings/save",
            "entry_id": entry.entry_id,
            "data": msg["result"]["data"],
        }
    )
    save = await client.receive_json()
    assert save["success"], save


async def test_settings_commands_require_admin(hass, hass_ws_client, hass_admin_user, entry):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    for command in ("get", "save"):
        payload = {"type": f"smartchain/settings/{command}", "entry_id": entry.entry_id}
        if command == "save":
            payload["data"] = {CONF_CHAT_MODEL: "gpt-4.1"}
        await client.send_json_auto_id(payload)
        msg = await client.receive_json()
        assert not msg["success"], command
        assert msg["error"]["code"] == "unauthorized", command


async def test_settings_responses_carry_no_credential(hass, hass_ws_client, entry):
    import json

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/settings/get", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    body = json.dumps(msg)
    assert SECRET not in body
    assert CONF_API_KEY not in body
