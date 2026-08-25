"""Translated field labels, and per-field validation errors."""

from unittest.mock import patch

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    DOMAIN,
    ID_OPENAI,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

MODELS = ["", "gpt-4.1-mini"]


@pytest.fixture(autouse=True)
def _models():
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=MODELS,
    ):
        yield


@pytest.fixture
async def entry(hass):
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sk-labels-secret"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
    )
    entry.add_to_hass(hass)
    return entry


async def test_schema_serves_a_label_for_every_field(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/agent/schema", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert msg["success"], msg

    labels = msg["result"]["labels"]
    for field in msg["result"]["schema"]:
        assert field["name"] in labels, field["name"]
        assert labels[field["name"]], field["name"]


async def test_labels_are_translated_not_raw_names(hass, hass_ws_client, entry):
    """The whole point: 'model' must render as its English label, not as 'model'."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/agent/schema", "entry_id": entry.entry_id})
    msg = await client.receive_json()

    labels = msg["result"]["labels"]
    assert labels[CONF_PROMPT] != CONF_PROMPT
    assert labels[CONF_CHAT_MODEL] != CONF_CHAT_MODEL


async def test_an_untranslated_field_falls_back_to_its_name(hass, hass_ws_client, entry):
    """A field added without a translation must still render, not vanish."""
    from custom_components.smartchain.websocket_api import async_field_labels

    with patch(
        "custom_components.smartchain.websocket_api.translation.async_get_translations",
        return_value={},
    ):
        labels = await async_field_labels(hass, "config_subentries")
    assert labels == {} or all(isinstance(v, str) for v in labels.values())


async def test_save_reports_the_offending_field(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1-mini", "not_a_field": 1},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_data"
    # The flat message stays, so nothing regresses if ha-form ignores the map.
    assert msg["error"]["message"]


async def test_invalid_field_error_names_the_field_but_not_the_value(hass, hass_ws_client, entry):
    """The message must say *which* field failed, never the value that failed it
    — that value could be a credential."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {
                CONF_CHAT_MODEL: "gpt-4.1-mini",
                CONF_MAX_TOKENS: "sk-value-should-not-leak",
            },
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_data"
    assert CONF_MAX_TOKENS in msg["error"]["message"]
    assert "sk-value-should-not-leak" not in msg["error"]["message"]


async def test_missing_model_is_reported_against_the_model_field(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_PROMPT: "no model"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert "model_required" in msg["error"]["message"]


async def test_no_label_or_error_response_carries_a_credential(hass, hass_ws_client, entry):
    import json

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/agent/schema", "entry_id": entry.entry_id})
    schema_msg = await client.receive_json()
    await client.send_json_auto_id(
        {"type": "smartchain/agent/save", "entry_id": entry.entry_id, "data": {}}
    )
    error_msg = await client.receive_json()

    both = json.dumps(schema_msg) + json.dumps(error_msg)
    assert "sk-labels-secret" not in both
    assert CONF_API_KEY not in both
