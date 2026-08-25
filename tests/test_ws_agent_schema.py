"""The websocket command that serialises the agent form schema."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentry, ConfigSubentryData
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENABLE_MULTI_AGENT_TOOLS,
    CONF_ENGINE,
    CONF_PROMPT,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
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


@pytest.fixture
async def entry_with_agent(hass):
    """A configured entry carrying one agent, for exercising the edit branch
    of ws_agent_schema (fetching by subentry_id) — the plain `entry` fixture
    above has no subentries and so never enters it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sekrit-key"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "carefully tuned"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    return entry


@pytest.fixture
async def entry_with_two_agents(hass):
    """Two agents, both carrying enable_multi_agent_tools — the flow only adds
    that field to the schema when 2+ subentries exist, so a real entry with
    two agents can plausibly have written it onto both. Reproduces F1."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sekrit-key"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={
                    CONF_CHAT_MODEL: "gpt-4.1-mini",
                    CONF_PROMPT: "first",
                    CONF_ENABLE_MULTI_AGENT_TOOLS: True,
                },
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="First",
                unique_id=None,
            ),
            ConfigSubentryData(
                data={
                    CONF_CHAT_MODEL: "gpt-4.1-mini",
                    CONF_PROMPT: "second",
                    CONF_ENABLE_MULTI_AGENT_TOOLS: True,
                },
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Second",
                unique_id=None,
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    return entry


async def test_schema_for_existing_agent_returns_its_data(hass, hass_ws_client, entry_with_agent):
    """The edit branch of ws_agent_schema was previously entered by no test at
    all — mutating `defaults` to `{}` for a known subentry_id survived every
    existing test. This enters it directly."""
    subentry_id = next(iter(entry_with_agent.subentries))
    client = await hass_ws_client(hass)
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ):
        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/schema",
                "entry_id": entry_with_agent.entry_id,
                "subentry_id": subentry_id,
            }
        )
        msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["data"][CONF_PROMPT] == "carefully tuned"
    assert msg["result"]["data"][CONF_CHAT_MODEL] == "gpt-4.1-mini"


async def test_deleting_a_sibling_does_not_break_the_survivors_save(
    hass, hass_ws_client, entry_with_two_agents
):
    """F1 reproducer. enable_multi_agent_tools is only declared in the schema
    when an entry has 2+ subentries. Delete one of two agents, both of which
    carry that key: the survivor's schema must stop serving the now-undeclared
    key, and saving exactly what the panel was served must succeed — Home
    Assistant's own dialog can save the same agent without complaint, so the
    panel must be able to as well."""
    entry = entry_with_two_agents
    survivor_id, doomed_id = list(entry.subentries)

    hass.config_entries.async_remove_subentry(entry, doomed_id)
    assert len(entry.subentries) == 1

    client = await hass_ws_client(hass)
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ):
        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/schema",
                "entry_id": entry.entry_id,
                "subentry_id": survivor_id,
            }
        )
        schema_msg = await client.receive_json()
        assert schema_msg["success"], schema_msg
        served_data = schema_msg["result"]["data"]

        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/save",
                "entry_id": entry.entry_id,
                "subentry_id": survivor_id,
                "data": served_data,
            }
        )
        save_msg = await client.receive_json()

    assert save_msg["success"], save_msg


async def test_schema_rejects_an_embeddings_subentry(hass, hass_ws_client, entry):
    """F2: schema must not resolve an embeddings subentry_id — save doesn't
    either, but nothing routes one through the panel UI except a client bug,
    same as the equivalent guard on duplicate/delete."""
    embeddings = ConfigSubentry(
        data={},
        subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
        title="Embeddings",
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, embeddings)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/schema",
            "entry_id": entry.entry_id,
            "subentry_id": embeddings.subentry_id,
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


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
    """Catches the handler serving a different schema than subentry_schema
    would, or serialisation silently dropping a field — it does not validate
    subentry_schema's own contents, so it is not a full single-source
    guarantee by itself."""
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
