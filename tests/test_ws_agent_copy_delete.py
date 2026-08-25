"""Duplicating and deleting agents through the panel's websocket API."""

import pytest
from homeassistant.config_entries import ConfigSubentry, ConfigSubentryData
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_PROMPT,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
async def entry(hass):
    """A configured OpenAI entry with one agent, and the domain set up so the
    websocket commands registered in async_setup() exist to be called."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
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


async def test_duplicate_copies_the_data_under_a_new_id(hass, hass_ws_client, entry):
    original_id = next(iter(entry.subentries))
    original = entry.subentries[original_id]

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/duplicate",
            "entry_id": entry.entry_id,
            "subentry_id": original_id,
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    copy_id = msg["result"]["subentry_id"]
    assert copy_id != original_id
    copy = entry.subentries[copy_id]
    assert dict(copy.data) == dict(original.data)
    assert copy.subentry_type == SUBENTRY_TYPE_CONVERSATION
    assert len(entry.subentries) == 2


async def test_duplicate_gives_the_copy_a_distinguishable_title(hass, hass_ws_client, entry):
    """Two agents with identical titles are unusable in a list."""
    original_id = next(iter(entry.subentries))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/duplicate",
            "entry_id": entry.entry_id,
            "subentry_id": original_id,
        }
    )
    msg = await client.receive_json()
    copy = entry.subentries[msg["result"]["subentry_id"]]
    assert copy.title != entry.subentries[original_id].title
    assert "Home" in copy.title


async def test_duplicate_leaves_the_original_untouched(hass, hass_ws_client, entry):
    original_id = next(iter(entry.subentries))
    before = dict(entry.subentries[original_id].data)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/duplicate",
            "entry_id": entry.entry_id,
            "subentry_id": original_id,
        }
    )
    await client.receive_json()
    assert dict(entry.subentries[original_id].data) == before


async def test_delete_removes_the_agent(hass, hass_ws_client, entry):
    target = next(iter(entry.subentries))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/delete",
            "entry_id": entry.entry_id,
            "subentry_id": target,
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert target not in entry.subentries


async def test_delete_of_an_unknown_agent_is_reported(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/delete",
            "entry_id": entry.entry_id,
            "subentry_id": "not-a-real-id",
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"
    assert len(entry.subentries) == 1


async def test_duplicating_twice_gives_all_three_titles_distinct(hass, hass_ws_client, entry):
    """The suffix exists to prevent identical titles, so the second use must
    not defeat it: duplicating "Home" twice must not produce two "Home
    (copy)" agents."""
    original_id = next(iter(entry.subentries))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/duplicate",
            "entry_id": entry.entry_id,
            "subentry_id": original_id,
        }
    )
    first = await client.receive_json()
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/duplicate",
            "entry_id": entry.entry_id,
            "subentry_id": original_id,
        }
    )
    second = await client.receive_json()
    assert first["success"] and second["success"], (first, second)

    second_copy = entry.subentries[second["result"]["subentry_id"]]
    titles = {
        entry.subentries[original_id].title,
        entry.subentries[first["result"]["subentry_id"]].title,
        second_copy.title,
    }
    assert len(titles) == 3
    # The fix must stay a readable title, not degrade into an opaque id.
    assert "Home" in second_copy.title


@pytest.mark.parametrize("command", ["duplicate", "delete"])
async def test_command_rejects_an_embeddings_subentry(hass, hass_ws_client, entry, command):
    """Neither command may reach an embeddings subentry.

    That guard is otherwise untested: nothing currently routes an embeddings
    subentry_id through these agent commands except a client bug, but the
    check in _resolve_agent exists to stop it, and D2 makes this reachable.
    _resolve_agent protects both commands today, but if it is ever split this
    test keeps both paths covered.
    """
    embeddings = ConfigSubentry(
        data={},
        subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
        title="Embeddings",
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, embeddings)
    before = set(entry.subentries)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"smartchain/agent/{command}",
            "entry_id": entry.entry_id,
            "subentry_id": embeddings.subentry_id,
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"
    # Rejected duplicate must create nothing; rejected delete must remove nothing.
    assert set(entry.subentries) == before


@pytest.mark.parametrize("command", ["duplicate", "delete"])
async def test_both_commands_require_admin(hass, hass_ws_client, hass_admin_user, entry, command):
    target = next(iter(entry.subentries))
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"smartchain/agent/{command}",
            "entry_id": entry.entry_id,
            "subentry_id": target,
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"
    assert len(entry.subentries) == 1
