"""Migrating a legacy entry's agent-shaped options into a real agent subentry.

The whole point of this migration is that nothing the user can see changes. The
legacy conversation entity's unique id is the config entry id; an agent's is
``f"{entry_id}_{subentry_id}"``. Letting a second entity appear would orphan
the old one and break every automation, script and dashboard card naming it —
so the registry row is rewritten in place, and the tests below are mostly about
proving the entity id survived.
"""

from functools import partial
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    ALL_TOOLS_SENTINEL,
    CONF_ALLOWED_TOOLS,
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_PROFANITY,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    CONF_VERIFY_SSL,
    DELEGATE_TOOL_NAME,
    DOMAIN,
    ENTITY_TOOL_NAME,
    ID_GIGACHAT,
    MEMORY_TOOL_NAME,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

LEGACY_OPTIONS = {
    CONF_CHAT_MODEL: "GigaChat-3-Ultra",
    CONF_PROMPT: "You are helpful.",
    CONF_TEMPERATURE: 0.4,
    CONF_VERIFY_SSL: False,
    CONF_PROFANITY: True,
}


def _legacy_entry(hass: HomeAssistant, *, options=None, subentries_data=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test-credentials"},
        options=dict(LEGACY_OPTIONS) if options is None else options,
        unique_id="GigaChat",
        title="GigaChat",
        minor_version=1,
        subentries_data=subentries_data or [],
    )
    entry.add_to_hass(hass)
    return entry


def _seed_entity(hass: HomeAssistant, domain: str, unique_id: str, object_id: str) -> str:
    """Register the entity a legacy install would already have."""
    return (
        er.async_get(hass)
        .async_get_or_create(
            domain,
            DOMAIN,
            unique_id,
            suggested_object_id=object_id,
        )
        .entity_id
    )


async def _setup(hass: HomeAssistant, entry, mock_llm_client) -> bool:
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        result = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return result


def _agents(entry) -> list:
    return [
        sub for sub in entry.subentries.values() if sub.subentry_type == SUBENTRY_TYPE_CONVERSATION
    ]


async def test_the_entity_id_survives(hass: HomeAssistant, mock_llm_client) -> None:
    """The test that matters most: the user's entity id does not move."""
    entry = _legacy_entry(hass)
    entity_id = _seed_entity(hass, "conversation", entry.entry_id, "my_assistant")
    assert entity_id == "conversation.my_assistant"

    assert await _setup(hass, entry, mock_llm_client)

    agents = _agents(entry)
    assert len(agents) == 1
    registry = er.async_get(hass)
    moved = registry.async_get("conversation.my_assistant")
    assert moved is not None
    assert moved.unique_id == f"{entry.entry_id}_{agents[0].subentry_id}"

    # And no second conversation entity appeared beside it.
    ours = [
        entity
        for entity in registry.entities.values()
        if entity.platform == DOMAIN and entity.domain == "conversation"
    ]
    assert [entity.entity_id for entity in ours] == ["conversation.my_assistant"]


async def test_the_ai_task_entity_moves_too(hass: HomeAssistant, mock_llm_client) -> None:
    """The second legacy unique id. Migrating one and orphaning the other is
    the same failure in a smaller costume."""
    entry = _legacy_entry(hass)
    _seed_entity(hass, "conversation", entry.entry_id, "my_assistant")
    _seed_entity(hass, "ai_task", f"{entry.entry_id}_ai_task", "my_assistant_ai_task")

    assert await _setup(hass, entry, mock_llm_client)

    sub_id = _agents(entry)[0].subentry_id
    registry = er.async_get(hass)
    moved = registry.async_get("ai_task.my_assistant_ai_task")
    assert moved is not None
    assert moved.unique_id == f"{entry.entry_id}_{sub_id}_ai_task"


async def test_options_become_an_agent(hass: HomeAssistant, mock_llm_client) -> None:
    """The agent carries the whole legacy config, connection switches included —
    `_resolve_client_args` forwards those per agent."""
    entry = _legacy_entry(hass)

    assert await _setup(hass, entry, mock_llm_client)

    agent = _agents(entry)[0]
    assert agent.title == "GigaChat-3-Ultra"
    # ... plus the explicit tool list minor version 3 writes. The legacy agent
    # had neither switch on, so it lists the sentinel and the four built-ins
    # that were never gated by one — exactly what it could call before.
    assert dict(agent.data) == {
        **LEGACY_OPTIONS,
        CONF_ALLOWED_TOOLS: [
            ALL_TOOLS_SENTINEL,
            DELEGATE_TOOL_NAME,
            MEMORY_TOOL_NAME,
            ENTITY_TOOL_NAME,
        ],
    }
    # The connection keeps only what belongs to the connection.
    assert dict(entry.options) == {CONF_VERIFY_SSL: False, CONF_PROFANITY: True}
    assert entry.minor_version == 3


async def test_an_entry_with_both_is_left_alone(hass: HomeAssistant, mock_llm_client) -> None:
    """Options plus agents: say so once, change nothing.

    Clearing the options would be tidier and is the one irreversible act
    available here, for data that costs nothing to leave alone.
    """
    entry = _legacy_entry(
        hass,
        subentries_data=[
            {
                "data": {CONF_CHAT_MODEL: "GigaChat"},
                "subentry_type": SUBENTRY_TYPE_CONVERSATION,
                "title": "Existing",
                "unique_id": None,
            }
        ],
    )

    assert await _setup(hass, entry, mock_llm_client)

    assert len(_agents(entry)) == 1
    assert _agents(entry)[0].title == "Existing"
    assert dict(entry.options) == LEGACY_OPTIONS


async def test_an_embeddings_subentry_does_not_count_as_an_agent(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """`if entry.subentries:` was the truthiness of the whole dict, so an
    embeddings-only entry read as "already has agents"."""
    entry = _legacy_entry(
        hass,
        subentries_data=[
            {
                "data": {"name": "vectors", "model": "Embeddings"},
                "subentry_type": SUBENTRY_TYPE_EMBEDDINGS,
                "title": "vectors",
                "unique_id": None,
            }
        ],
    )

    assert await _setup(hass, entry, mock_llm_client)

    assert len(_agents(entry)) == 1


async def test_an_entry_with_neither_is_untouched(hass: HomeAssistant, mock_llm_client) -> None:
    """A connection-only entry migrates to the current minor version and gains nothing."""
    entry = _legacy_entry(hass, options={})

    assert await _setup(hass, entry, mock_llm_client)

    assert _agents(entry) == []
    assert dict(entry.options) == {}
    assert entry.minor_version == 3
    assert [
        entity
        for entity in er.async_get(hass).entities.values()
        if entity.platform == DOMAIN and entity.domain == "conversation"
    ] == []


async def test_a_second_setup_does_not_migrate_twice(hass: HomeAssistant, mock_llm_client) -> None:
    entry = _legacy_entry(hass)
    _seed_entity(hass, "conversation", entry.entry_id, "my_assistant")

    assert await _setup(hass, entry, mock_llm_client)
    first = _agents(entry)[0].subentry_id

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    agents = _agents(entry)
    assert len(agents) == 1
    assert agents[0].subentry_id == first
    assert er.async_get(hass).async_get("conversation.my_assistant") is not None


async def test_a_refused_migration_leaves_the_entry_exactly_as_it_was(
    hass: HomeAssistant, mock_llm_client, caplog
) -> None:
    """A silent rename that breaks someone's automations is far worse than
    carrying the old path another release."""
    entry = _legacy_entry(hass)
    _seed_entity(hass, "conversation", entry.entry_id, "my_assistant")

    # Any rewrite of the conversation entity fails, however it is called.
    real_update = er.EntityRegistry.async_update_entity

    def _boom(self, entity_id, **kwargs):
        if "new_unique_id" in kwargs and entity_id == "conversation.my_assistant":
            raise ValueError("Unique id is already in use")
        return real_update(self, entity_id, **kwargs)

    with patch.object(er.EntityRegistry, "async_update_entity", _boom):
        assert await _setup(hass, entry, mock_llm_client)

    assert _agents(entry) == []
    assert dict(entry.options) == LEGACY_OPTIONS
    assert entry.minor_version == 1
    assert "refusing to migrate" in caplog.text
    # Refusing must degrade nothing: the entry keeps its legacy entity.
    moved = er.async_get(hass).async_get("conversation.my_assistant")
    assert moved.unique_id == entry.entry_id
    assert entry.runtime_data is mock_llm_client


async def test_a_refused_migration_puts_back_a_rename_it_already_made(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """Conversation moves, AI Task then fails: the first move must be undone,
    or the refusal orphans exactly what it was protecting."""
    entry = _legacy_entry(hass)
    _seed_entity(hass, "conversation", entry.entry_id, "my_assistant")
    _seed_entity(hass, "ai_task", f"{entry.entry_id}_ai_task", "my_assistant_ai_task")

    real_update = er.EntityRegistry.async_update_entity

    def _boom(self, entity_id, **kwargs):
        if "new_unique_id" in kwargs and entity_id == "ai_task.my_assistant_ai_task":
            raise ValueError("Unique id is already in use")
        return real_update(self, entity_id, **kwargs)

    with patch.object(er.EntityRegistry, "async_update_entity", _boom):
        assert await _setup(hass, entry, mock_llm_client)

    registry = er.async_get(hass)
    assert _agents(entry) == []
    assert entry.minor_version == 1
    assert registry.async_get("conversation.my_assistant").unique_id == entry.entry_id
    assert (
        registry.async_get("ai_task.my_assistant_ai_task").unique_id == f"{entry.entry_id}_ai_task"
    )


async def test_a_collision_really_does_refuse(hass: HomeAssistant, mock_llm_client) -> None:
    """Not a mock: an entity already holding a plausible target unique id.

    The registry raises on a duplicate unique id, and the migration must treat
    that as a refusal rather than a rename to guess at.
    """
    entry = _legacy_entry(hass)
    _seed_entity(hass, "conversation", entry.entry_id, "my_assistant")
    # Pre-claim the unique id the migration is about to want.
    _seed_entity(hass, "conversation", f"{entry.entry_id}_TAKEN", "someone_else")

    fixed_id = partial(ConfigSubentry, subentry_id="TAKEN")
    with patch("custom_components.smartchain.ConfigSubentry", fixed_id):
        assert await _setup(hass, entry, mock_llm_client)

    assert _agents(entry) == []
    assert entry.minor_version == 1
    assert er.async_get(hass).async_get("conversation.my_assistant").unique_id == entry.entry_id
