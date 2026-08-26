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


async def test_schema_serves_a_description_for_every_field(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/agent/schema", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert msg["success"], msg

    descriptions = msg["result"]["descriptions"]
    for field in msg["result"]["schema"]:
        assert field["name"] in descriptions, field["name"]
        assert descriptions[field["name"]], field["name"]


async def test_settings_schema_serves_a_description_for_every_field(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/settings/get", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert msg["success"], msg

    descriptions = msg["result"]["descriptions"]
    for field in msg["result"]["schema"]:
        assert field["name"] in descriptions, field["name"]
        assert descriptions[field["name"]], field["name"]


async def test_an_untranslated_field_has_no_description_but_the_response_still_renders(
    hass, hass_ws_client, entry
):
    """A field with no `data_description` must be absent from the map, not
    fabricated — and the schema command must still succeed rather than break
    on the gap, mirroring the fallback the panel applies to an empty string."""
    from custom_components.smartchain.websocket_api import async_field_descriptions

    prefix = "component.smartchain.config_subentries.conversation.step.user.data_description"
    resources = {f"{prefix}.prompt": "What the model is told before every message."}
    with patch(
        "custom_components.smartchain.websocket_api.translation.async_get_translations",
        return_value=resources,
    ):
        descriptions = await async_field_descriptions(hass, "config_subentries")

    assert descriptions[CONF_PROMPT] == "What the model is told before every message."
    assert CONF_MAX_TOKENS not in descriptions
    assert CONF_CHAT_MODEL not in descriptions

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/agent/schema", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert msg["success"], msg


async def test_labels_are_translated_not_raw_names(hass, hass_ws_client, entry):
    """The whole point: 'model' must render as its English label, not as 'model'."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/agent/schema", "entry_id": entry.entry_id})
    msg = await client.receive_json()

    labels = msg["result"]["labels"]
    assert labels[CONF_PROMPT] != CONF_PROMPT
    assert labels[CONF_CHAT_MODEL] != CONF_CHAT_MODEL


async def test_an_untranslated_field_is_absent_not_fabricated(hass, hass_ws_client, entry):
    """A field with no translation must be missing from the map — the panel
    falls back to the raw name; the backend must not paper over the gap."""
    from custom_components.smartchain.websocket_api import async_field_labels

    prefix = "component.smartchain.config_subentries.conversation.step.user.data"
    resources = {
        f"{prefix}.prompt": "Prompt",
        f"{prefix}.model": "Completion Model",
    }
    with patch(
        "custom_components.smartchain.websocket_api.translation.async_get_translations",
        return_value=resources,
    ):
        labels = await async_field_labels(hass, "config_subentries")

    assert labels[CONF_PROMPT] == "Prompt"
    assert labels[CONF_CHAT_MODEL] == "Completion Model"
    assert CONF_MAX_TOKENS not in labels


async def test_save_names_the_offending_field(hass, hass_ws_client, entry):
    """A message that does not name the field leaves the user hunting for it."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_MAX_TOKENS: "not-a-number"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_data"
    assert CONF_MAX_TOKENS in msg["error"]["message"]


async def test_a_rejected_value_never_appears_in_the_message(hass, hass_ws_client, entry):
    """The message reports which field failed, never what was in it."""
    import json

    marker = "sk-this-must-never-be-echoed"
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_MAX_TOKENS: marker},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert marker not in json.dumps(msg)


async def test_missing_model_is_reported_against_the_model_field(hass, hass_ws_client, entry):
    """Named fields and a sentence — the two halves the panel needs.

    `<sc-config-form>` attaches an error to a control by matching the field
    list against the schema it rendered, and shows the text after the em dash.
    A message with neither, which is what "model_required" was, can only be
    toasted as a machine key.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/agent/schema", "entry_id": entry.entry_id})
    schema_msg = await client.receive_json()
    declared = {field["name"] for field in schema_msg["result"]["schema"]}

    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_PROMPT: "no model"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    message = msg["error"]["message"]
    fields, _, text = message.removeprefix("invalid_data: ").partition(" — ")
    named = [name.strip() for name in fields.split(",")]
    assert named, message
    assert set(named) <= declared, "the panel can only attach a field its schema declares"
    assert text and "model_required" not in text


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
