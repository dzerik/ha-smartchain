"""MemoryRegistry resolves embeddings references and owns per-store tasks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
)
from custom_components.smartchain.tools.memory.config import (
    MemorySettings,
    StoreConfig,
)
from custom_components.smartchain.tools.memory.registry import MemoryRegistry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _entry_with_embeddings(hass: HomeAssistant, titles: list[str]) -> MockConfigEntry:
    from homeassistant.config_entries import ConfigSubentryData

    from custom_components.smartchain.const import SUBENTRY_TYPE_EMBEDDINGS

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
        subentries_data=[
            ConfigSubentryData(
                data={"model": "Embeddings"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title=title,
                unique_id=None,
            )
            for title in titles
        ],
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def patched_store():
    """Patch MemoryStore so no real backend or embeddings provider is needed."""
    made: list[MagicMock] = []

    def _factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.backend = backend
        made.append(st)
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
        yield made


async def test_build_resolves_reference_by_title(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["GigaChat Embeddings"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[StoreConfig(name="conversations", embeddings="GigaChat Embeddings")]
        ),
        tmp_path,
    )
    assert registry.names() == ["conversations"]
    assert registry.get("conversations") is not None
    await registry.shutdown()


async def test_missing_reference_skips_only_that_store(
    hass: HomeAssistant, tmp_path, patched_store, caplog
) -> None:
    _entry_with_embeddings(hass, ["GigaChat Embeddings"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="good", embeddings="GigaChat Embeddings"),
                StoreConfig(name="bad", embeddings="Does Not Exist"),
            ]
        ),
        tmp_path,
    )
    assert registry.names() == ["good"]
    assert "Does Not Exist" in caplog.text
    assert "GigaChat Embeddings" in caplog.text  # available titles are listed
    await registry.shutdown()


async def test_duplicate_titles_skip_the_store(
    hass: HomeAssistant, tmp_path, patched_store, caplog
) -> None:
    _entry_with_embeddings(hass, ["Dup", "Dup"])
    registry = MemoryRegistry(hass)
    await registry.build(MemorySettings(stores=[StoreConfig(name="s", embeddings="Dup")]), tmp_path)
    assert registry.names() == []
    assert "duplicate" in caplog.text.lower()
    await registry.shutdown()


async def test_get_none_returns_single_store(hass: HomeAssistant, tmp_path, patched_store) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(stores=[StoreConfig(name="only", embeddings="E")]), tmp_path
    )
    assert registry.get(None) is registry.get("only")
    await registry.shutdown()


async def test_get_none_is_ambiguous_with_two_stores(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="a", embeddings="E"),
                StoreConfig(name="b", embeddings="E"),
            ]
        ),
        tmp_path,
    )
    assert registry.get(None) is None
    await registry.shutdown()


async def test_unavailable_store_is_not_registered(hass: HomeAssistant, tmp_path) -> None:
    _entry_with_embeddings(hass, ["E"])

    def _factory(hass_, embeddings, backend):
        st = MagicMock()
        st.is_available = False
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
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
        registry = MemoryRegistry(hass)
        await registry.build(
            MemorySettings(stores=[StoreConfig(name="s", embeddings="E")]), tmp_path
        )
    assert registry.names() == []
    await registry.shutdown()


async def test_describe_returns_names_and_descriptions(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(stores=[StoreConfig(name="a", embeddings="E", description="First store")]),
        tmp_path,
    )
    assert registry.describe() == [("a", "First store")]
    await registry.shutdown()


async def test_conversation_ingest_targets_respect_the_flag(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="yes", embeddings="E", ingest_conversation=True),
                StoreConfig(name="no", embeddings="E", ingest_conversation=False),
            ]
        ),
        tmp_path,
    )
    targets = registry.stores_for_conversation_ingest()
    assert len(targets) == 1
    assert targets[0] is registry.get("yes")
    await registry.shutdown()


async def test_shutdown_closes_every_store(hass: HomeAssistant, tmp_path, patched_store) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="a", embeddings="E"),
                StoreConfig(name="b", embeddings="E"),
            ]
        ),
        tmp_path,
    )
    await registry.shutdown()

    assert registry.names() == []
    for store in patched_store:
        store.close.assert_awaited()
