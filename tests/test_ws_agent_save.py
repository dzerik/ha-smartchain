"""Creating and updating an agent through the panel's websocket API."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentry, ConfigSubentryData
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENGINE,
    CONF_PROMPT,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

MODELS = ["", "gpt-4.1-mini", "gpt-4.1"]
API_KEY = "sk-panel-save-secret"


@pytest.fixture(autouse=True)
def _models():
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=MODELS,
    ):
        yield


@pytest.fixture
async def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: API_KEY},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "old"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="gpt-4.1-mini",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    return entry


async def test_save_creates_an_agent(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1", CONF_PROMPT: "hello"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    # Verify against the real store, not the response.
    created = entry.subentries[msg["result"]["subentry_id"]]
    assert created.subentry_type == SUBENTRY_TYPE_CONVERSATION
    assert created.data[CONF_CHAT_MODEL] == "gpt-4.1"
    assert created.data[CONF_PROMPT] == "hello"
    assert created.title == "gpt-4.1"


async def test_save_updates_an_existing_agent(hass, hass_ws_client, entry):
    existing = next(iter(entry.subentries))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "subentry_id": existing,
            "data": {CONF_CHAT_MODEL: "gpt-4.1", CONF_PROMPT: "new"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["subentry_id"] == existing

    updated = entry.subentries[existing]
    assert updated.data[CONF_PROMPT] == "new"
    assert updated.title == "gpt-4.1"
    assert len(entry.subentries) == 1, "an update must not create a second agent"


async def test_save_rejects_input_with_no_model(hass, hass_ws_client, entry):
    """Validation parity: what the flow rejects, this must reject the same way.

    And it must say so the way a person can act on. `DEFAULT_CHAT_MODEL` is "",
    so "+ Agent" opens with nothing selected and this is the very first Save a
    new user ever performs — it used to answer with the bare key
    "model_required", which the panel could not attach to a field and toasted
    verbatim.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_PROMPT: "no model here"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_data"
    message = msg["error"]["message"]
    assert message.startswith("invalid_data: "), message
    fields, _, text = message.removeprefix("invalid_data: ").partition(" — ")
    assert [name.strip() for name in fields.split(",")] == [CONF_CHAT_MODEL, CONF_CHAT_MODEL_USER]
    # The sentence the config flow shows for this rule, not its key.
    assert text == "Either Model or Custom Model required"
    assert "model_required" not in message
    assert len(entry.subentries) == 1, "a rejected save must create nothing"


async def test_save_rejects_a_field_the_schema_forbids(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1", "not_a_real_field": 1},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_data"


async def test_save_on_unknown_entry_is_reported(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": "nope",
            "data": {CONF_CHAT_MODEL: "gpt-4.1"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_save_requires_admin(hass, hass_ws_client, hass_admin_user, entry):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"


async def test_save_rejects_an_embeddings_subentry(hass, hass_ws_client, entry):
    """F2: save must not resolve an embeddings subentry_id — overwriting its
    name/model and retitling it would break the title-based binding the
    memory store relies on. Not reachable from the panel UI today, but the
    guard is the same one duplicate/delete already use."""
    embeddings = ConfigSubentry(
        data={"name": "Embeddings", "model": "text-embedding-3-small"},
        subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
        title="Embeddings",
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, embeddings)
    before_data = dict(embeddings.data)
    before_title = embeddings.title

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "subentry_id": embeddings.subentry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"
    assert dict(embeddings.data) == before_data
    assert embeddings.title == before_title


async def test_error_message_carries_no_credential(hass, hass_ws_client, entry):
    import json

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/agent/save", "entry_id": entry.entry_id, "data": {}}
    )
    msg = await client.receive_json()
    dumped = json.dumps(msg)
    assert API_KEY not in dumped
    assert CONF_API_KEY not in dumped
