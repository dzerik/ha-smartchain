"""Entry connection settings over the panel's websocket API.

An entry is a connection, so these commands serve `connection_schema` — not the
agent form. For most providers that schema is empty, and the honest answer is
`empty: true` rather than a form with no fields in it.
"""

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_PROFANITY,
    CONF_PROMPT,
    CONF_VERIFY_SSL,
    DOMAIN,
    ID_GIGACHAT,
    ID_OPENAI,
    UNIQUE_ID_GIGACHAT,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SECRET = "sk-settings-secret"


@pytest.fixture
async def entry(hass):
    """An OpenAI entry — a provider with no connection settings at all."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET},
        options={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "current"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def gigachat_entry(hass):
    """A GigaChat entry — the one provider that has connection settings."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: SECRET},
        options={CONF_VERIFY_SSL: False, CONF_CHAT_MODEL: "GigaChat-Legacy"},
        unique_id=UNIQUE_ID_GIGACHAT,
        title=UNIQUE_ID_GIGACHAT,
        minor_version=2,
    )
    entry.add_to_hass(hass)
    return entry


async def test_get_serves_the_connection_settings(hass, hass_ws_client, gigachat_entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/settings/get", "entry_id": gigachat_entry.entry_id}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["empty"] is False
    names = {field["name"] for field in msg["result"]["schema"]}
    assert names == {CONF_VERIFY_SSL, CONF_PROFANITY}
    assert msg["result"]["data"][CONF_VERIFY_SSL] is False
    assert msg["result"]["labels"]


async def test_get_never_serves_an_agent_field(hass, hass_ws_client, gigachat_entry):
    """The entry still holds a legacy agent option; it must not be presented."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/settings/get", "entry_id": gigachat_entry.entry_id}
    )
    msg = await client.receive_json()
    assert CONF_CHAT_MODEL not in msg["result"]["data"]
    assert CONF_CHAT_MODEL not in {field["name"] for field in msg["result"]["schema"]}


async def test_get_reports_a_provider_with_no_connection_settings(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/settings/get", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["empty"] is True
    assert msg["result"]["schema"] == []
    assert msg["result"]["data"] == {}


async def test_save_writes_to_options_and_never_to_data(hass, hass_ws_client, gigachat_entry):
    """Settings live in options. Writing them into data would put them where
    the provider credential lives."""
    before = dict(gigachat_entry.data)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/settings/save",
            "entry_id": gigachat_entry.entry_id,
            "data": {CONF_VERIFY_SSL: True, CONF_PROFANITY: True},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    assert gigachat_entry.options[CONF_VERIFY_SSL] is True
    assert gigachat_entry.options[CONF_PROFANITY] is True
    assert dict(gigachat_entry.data) == before


async def test_save_leaves_unpresented_options_alone(hass, hass_ws_client, gigachat_entry):
    """A legacy option the connection form does not present must survive a save."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/settings/save",
            "entry_id": gigachat_entry.entry_id,
            "data": {CONF_VERIFY_SSL: True, CONF_PROFANITY: False},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert gigachat_entry.options[CONF_CHAT_MODEL] == "GigaChat-Legacy"


async def test_save_refuses_a_provider_with_no_connection_settings(hass, hass_ws_client, entry):
    before = dict(entry.options)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/settings/save",
            "entry_id": entry.entry_id,
            "data": {CONF_VERIFY_SSL: True},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"], msg
    assert msg["error"]["code"] == "not_supported"
    assert dict(entry.options) == before


async def test_save_rejects_an_undeclared_field(hass, hass_ws_client, gigachat_entry):
    before = dict(gigachat_entry.options)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/settings/save",
            "entry_id": gigachat_entry.entry_id,
            "data": {CONF_CHAT_MODEL: "GigaChat"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"], msg
    assert msg["error"]["code"] == "invalid_data"
    assert dict(gigachat_entry.options) == before


async def test_get_serves_only_declared_fields(hass, hass_ws_client, gigachat_entry):
    """The trap D1 hit: a served key the schema does not declare makes the form
    permanently unsavable, because save uses PREVENT_EXTRA."""
    hass.config_entries.async_update_entry(
        gigachat_entry, options={**gigachat_entry.options, "a_field_no_schema_declares": True}
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/settings/get", "entry_id": gigachat_entry.entry_id}
    )
    msg = await client.receive_json()
    assert "a_field_no_schema_declares" not in msg["result"]["data"]

    # And what was served must round-trip.
    await client.send_json_auto_id(
        {
            "type": "smartchain/settings/save",
            "entry_id": gigachat_entry.entry_id,
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
            payload["data"] = {CONF_VERIFY_SSL: True}
        await client.send_json_auto_id(payload)
        msg = await client.receive_json()
        assert not msg["success"], command
        assert msg["error"]["code"] == "unauthorized", command


async def test_settings_responses_carry_no_credential(hass, hass_ws_client, gigachat_entry):
    import json

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/settings/get", "entry_id": gigachat_entry.entry_id}
    )
    msg = await client.receive_json()
    body = json.dumps(msg)
    assert SECRET not in body
    assert CONF_API_KEY not in body
