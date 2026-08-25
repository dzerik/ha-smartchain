"""The overview command that lists entries and their agents."""

import json

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_ALLOWED_TOOLS,
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENGINE,
    CONF_FOLDER_ID,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SECRET = "sk-do-not-leak-me"
FOLDER = "folder-do-not-leak-me"


@pytest.fixture
async def entry(hass):
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET, CONF_FOLDER_ID: FOLDER},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_overview_lists_the_entry_and_its_agent(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    assert msg["success"], msg
    entries = msg["result"]["entries"]
    assert len(entries) == 1
    served = entries[0]
    assert served["entry_id"] == entry.entry_id
    assert served["engine"] == ID_OPENAI
    assert served["engine_label"] == UNIQUE_ID_OPENAI
    assert served["supports_embeddings"] is True

    agents = served["agents"]
    assert len(agents) == 1
    assert agents[0]["title"] == "Home"
    assert agents[0]["model"] == "gpt-4.1-mini"
    assert "tool_count" in agents[0]


async def test_overview_never_carries_a_credential(hass, hass_ws_client, entry):
    """The whole response, serialised, must contain no secret from entry data."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    body = json.dumps(msg)
    assert SECRET not in body
    assert FOLDER not in body
    # Nor the key names, which would mean entry data was forwarded wholesale.
    assert CONF_API_KEY not in body


async def test_overview_requires_admin(hass, hass_ws_client, hass_admin_user, entry):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"


async def test_overview_with_no_entries_is_an_empty_list(hass, hass_ws_client):
    await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["entries"] == []


async def test_embeddings_capability_follows_the_provider(hass, hass_ws_client):
    """A provider without embeddings must say so — D2 hides a tab on this."""
    from custom_components.smartchain.const import ID_ANTHROPIC, UNIQUE_ID_ANTHROPIC

    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_ANTHROPIC, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_ANTHROPIC,
        title=UNIQUE_ID_ANTHROPIC,
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    served = next(e for e in msg["result"]["entries"] if e["entry_id"] == entry.entry_id)
    assert served["supports_embeddings"] is False


async def test_tool_count_is_none_when_unrestricted(hass, hass_ws_client, entry):
    """No allowed_tools key means every tool; the panel shows "all tools"."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agent = msg["result"]["entries"][0]["agents"][0]
    assert agent["tool_count"] is None


async def test_tool_count_is_zero_when_restricted_to_nothing(hass, hass_ws_client):
    """An explicit empty list means no tool at all — the opposite of None."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_ALLOWED_TOOLS: []},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="No Tools",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agent = msg["result"]["entries"][0]["agents"][0]
    assert agent["tool_count"] == 0


async def test_tool_count_counts_a_restricted_list(hass, hass_ws_client):
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_ALLOWED_TOOLS: ["a", "b"]},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Two Tools",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agent = msg["result"]["entries"][0]["agents"][0]
    assert agent["tool_count"] == 2


async def test_agents_excludes_non_conversation_subentries(hass, hass_ws_client):
    """An embeddings subentry on the same entry must not show up as an agent."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            ),
            ConfigSubentryData(
                data={},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="Embeddings",
                unique_id=None,
            ),
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agents = msg["result"]["entries"][0]["agents"]
    assert len(agents) == 1
    assert agents[0]["title"] == "Home"


async def test_model_falls_back_when_model_user_is_whitespace(hass, hass_ws_client):
    """A whitespace-only override must not shadow the real model — a truthiness
    check on the raw string would wrongly treat "   " as a set override."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_CHAT_MODEL_USER: "   "},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agent = msg["result"]["entries"][0]["agents"][0]
    assert agent["model"] == "gpt-4.1-mini"
