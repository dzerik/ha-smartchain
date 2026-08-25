"""The websocket command that serialises the agent form schema."""

from unittest.mock import patch

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_OPENAI,
    UNIQUE_ID_OPENAI,
)

# Needed so hass can discover custom_components/smartchain at all, and so the
# domain-level async_setup() below (which registers the websocket command)
# actually runs — plain entry.add_to_hass() does not trigger it.
pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
async def entry(hass):
    """A configured OpenAI entry, with the domain set up so the websocket
    command registered in async_setup() exists to be called."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sekrit-key"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    return entry


async def test_schema_command_returns_renderable_fields(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ):
        await client.send_json_auto_id(
            {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
        )
        msg = await client.receive_json()

    assert msg["success"], msg
    fields = msg["result"]["schema"]
    assert fields, "an empty schema would render an empty form"
    # Every entry ha-form can render carries a name and either a plain type or
    # a selector; anything else would silently render as nothing.
    for field in fields:
        assert field.get("name"), field
        assert "type" in field or "selector" in field, field


async def test_schema_matches_the_config_flow_schema(hass, hass_ws_client, entry):
    """The single-source guarantee: the panel sees exactly the flow's fields."""
    from custom_components.smartchain.config_flow import subentry_schema

    client = await hass_ws_client(hass)
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ):
        await client.send_json_auto_id(
            {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
        )
        msg = await client.receive_json()

    served = {f["name"] for f in msg["result"]["schema"]}
    expected = {
        str(key.schema)
        for key in subentry_schema(hass, UNIQUE_ID_OPENAI, {}, models=["", "gpt-4.1-mini"]).schema
    }
    assert served == expected


async def test_schema_carries_no_credential(hass, hass_ws_client, entry):
    import json

    client = await hass_ws_client(hass)
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ):
        await client.send_json_auto_id(
            {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
        )
        msg = await client.receive_json()

    assert "sekrit-key" not in json.dumps(msg)


async def test_schema_requires_admin(hass, hass_ws_client, hass_admin_user, entry):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/agent/schema", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"


async def test_unknown_entry_is_reported_not_crashed(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/agent/schema", "entry_id": "does-not-exist"}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_models_are_cached_until_refresh_is_asked_for(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ) as fetch:
        for _ in range(3):
            await client.send_json_auto_id(
                {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
            )
            await client.receive_json()
        assert fetch.call_count == 1

        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/schema",
                "entry_id": entry.entry_id,
                "refresh": True,
            }
        )
        await client.receive_json()
        assert fetch.call_count == 2
