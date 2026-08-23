"""Tests for the smartchain.clear_memory service."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain import async_setup
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    EVENT_MEMORY_CLEARED,
    ID_GIGACHAT,
    SERVICE_CLEAR_MEMORY,
    SUBENTRY_TYPE_EMBEDDINGS,
)
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer, SweepResult

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
def tools_dir(hass: HomeAssistant, tmp_path_factory) -> Path:
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    hass.config.config_dir = str(cdir)
    return cdir / "smartchain"


@pytest.fixture
def patched_store():
    """Patch the registry's collaborators so no real backend is opened."""

    def _factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.clear = AsyncMock(return_value=4)
        return st

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry.create_embeddings_from_subentry",
            return_value=MagicMock(),
        ),
    ):
        yield


def _add_embeddings_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
        subentries_data=[
            ConfigSubentryData(
                data={"model": "Embeddings"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="GigaChat Embeddings",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_clear_memory_without_config_raises(hass: HomeAssistant, tools_dir: Path) -> None:
    """With no memory: block in YAML the registry is empty and the service raises."""
    (tools_dir / "tools.yaml").write_text("tools: []\n")
    await async_setup(hass, {})

    registry = hass.data[DOMAIN]["memory"]
    assert registry.names() == []

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, SERVICE_CLEAR_MEMORY, {}, blocking=True)


async def test_clear_memory_fires_event(
    hass: HomeAssistant, tools_dir: Path, patched_store
) -> None:
    """When a store is configured, clear fires EVENT_MEMORY_CLEARED with the deleted count."""
    (tools_dir / "tools.yaml").write_text(
        "tools: []\n"
        "memory:\n"
        "  stores:\n"
        "    - name: conversations\n"
        '      embeddings: "GigaChat Embeddings"\n'
    )
    _add_embeddings_entry(hass)

    await async_setup(hass, {})
    assert hass.data[DOMAIN]["memory"].names() == ["conversations"]

    events: list = []
    hass.bus.async_listen(EVENT_MEMORY_CLEARED, lambda e: events.append(e))

    await hass.services.async_call(
        DOMAIN, SERVICE_CLEAR_MEMORY, {"kind": "conversation"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["deleted"] == 4
    assert events[0].data["stores"] == ["conversations"]


_TWO_STORES_YAML = """
tools: []
memory:
  stores:
    - name: conversations
      embeddings: "GigaChat Embeddings"
    - name: entities
      embeddings: "GigaChat Embeddings"
"""


@pytest.fixture
def two_stores(hass: HomeAssistant, tools_dir: Path):
    """Two configured stores, each backed by a mock that reports 3 deletions."""
    (tools_dir / "tools.yaml").write_text(_TWO_STORES_YAML)
    _add_embeddings_entry(hass)

    def _factory(hass_, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.clear = AsyncMock(return_value=3)
        return st

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry.create_embeddings_from_subentry",
            return_value=MagicMock(),
        ),
    ):
        yield


async def test_clear_memory_targets_one_store(hass: HomeAssistant, two_stores) -> None:
    """Passing `store` clears only that store."""
    await async_setup(hass, {})

    events: list = []
    hass.bus.async_listen(EVENT_MEMORY_CLEARED, lambda e: events.append(e))

    await hass.services.async_call(
        DOMAIN, SERVICE_CLEAR_MEMORY, {"store": "conversations"}, blocking=True
    )
    await hass.async_block_till_done()

    assert events[0].data["stores"] == ["conversations"]
    assert events[0].data["deleted"] == 3


async def test_clear_memory_without_store_clears_all(hass: HomeAssistant, two_stores) -> None:
    """With no `store` the service clears every configured store."""
    await async_setup(hass, {})

    events: list = []
    hass.bus.async_listen(EVENT_MEMORY_CLEARED, lambda e: events.append(e))

    await hass.services.async_call(DOMAIN, SERVICE_CLEAR_MEMORY, {}, blocking=True)
    await hass.async_block_till_done()

    assert sorted(events[0].data["stores"]) == ["conversations", "entities"]
    assert events[0].data["deleted"] == 6


async def test_clear_memory_unknown_store_raises(hass: HomeAssistant, two_stores) -> None:
    """Naming a store that is not configured is an error, not a silent no-op."""
    await async_setup(hass, {})

    # Assert the registry actually built: without this the empty-registry guard
    # would raise the same error and the unknown-store guard would go untested.
    assert sorted(hass.data[DOMAIN]["memory"].names()) == ["conversations", "entities"]

    with pytest.raises(HomeAssistantError, match="unknown memory store"):
        await hass.services.async_call(
            DOMAIN, SERVICE_CLEAR_MEMORY, {"store": "ghost"}, blocking=True
        )


_ENTITY_AND_CONVERSATION_YAML = """
tools: []
memory:
  stores:
    - name: entities
      embeddings: "GigaChat Embeddings"
      source:
        type: entities
        preset: minimal
    - name: conversations
      embeddings: "GigaChat Embeddings"
"""


@pytest.fixture
def patched_indexer():
    """Patch EntityIndexer so `entities` gets an indexer without doing real work."""
    with patch(
        "custom_components.smartchain.tools.memory.registry.EntityIndexer",
        spec=EntityIndexer,
    ) as indexer_cls:
        indexer_cls.return_value.start = MagicMock()
        indexer_cls.return_value.stop = AsyncMock()
        indexer_cls.return_value.reconcile = AsyncMock(return_value=SweepResult())
        yield indexer_cls


async def test_clear_memory_triggers_a_sweep_for_an_indexed_store(
    hass: HomeAssistant, tools_dir: Path, patched_store, patched_indexer
) -> None:
    """Clearing a `kind: entity` store outside the indexer must not leave the
    index stale forever — clear_memory schedules a reconciling sweep."""
    (tools_dir / "tools.yaml").write_text(_ENTITY_AND_CONVERSATION_YAML)
    _add_embeddings_entry(hass)
    await async_setup(hass, {})
    assert hass.data[DOMAIN]["memory"].indexer_for("entities") is not None

    await hass.services.async_call(
        DOMAIN, SERVICE_CLEAR_MEMORY, {"store": "entities"}, blocking=True
    )
    await hass.async_block_till_done()

    patched_indexer.return_value.reconcile.assert_awaited_once_with()


async def test_clear_memory_does_not_sweep_a_conversation_store(
    hass: HomeAssistant, tools_dir: Path, patched_store, patched_indexer
) -> None:
    """A plain conversation store has no indexer, so no sweep is scheduled for it."""
    (tools_dir / "tools.yaml").write_text(_ENTITY_AND_CONVERSATION_YAML)
    _add_embeddings_entry(hass)
    await async_setup(hass, {})
    assert hass.data[DOMAIN]["memory"].indexer_for("conversations") is None

    await hass.services.async_call(
        DOMAIN, SERVICE_CLEAR_MEMORY, {"store": "conversations"}, blocking=True
    )
    await hass.async_block_till_done()

    patched_indexer.return_value.reconcile.assert_not_awaited()
