"""End-to-end multi-store wiring through hass.data."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
    SUBENTRY_TYPE_EMBEDDINGS,
)
from custom_components.smartchain.tools.memory.registry import MemoryRegistry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

_YAML = """
tools: []
memory:
  stores:
    - name: conversations
      description: "Dialogue history"
      embeddings: "GigaChat Embeddings"
      ingest_conversation: true
    - name: entities
      description: "Devices"
      embeddings: "GigaChat Embeddings"
      ingest_conversation: false
"""


@pytest.fixture
def patched_store():
    def _factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.add = AsyncMock(return_value=["id"])
        st.search = AsyncMock(return_value=[])
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


async def _setup(hass: HomeAssistant, tmp_path_factory, mock_llm_client):
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text(_YAML)
    hass.config.config_dir = str(cdir)

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

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_registry_lands_in_hass_data(
    hass: HomeAssistant, mock_llm_client, tmp_path_factory, patched_store
) -> None:
    await _setup(hass, tmp_path_factory, mock_llm_client)
    registry = hass.data[DOMAIN]["memory"]
    assert isinstance(registry, MemoryRegistry)
    assert sorted(registry.names()) == ["conversations", "entities"]


async def test_registry_is_rebuilt_after_an_entry_reload(
    hass: HomeAssistant, mock_llm_client, tmp_path_factory, patched_store
) -> None:
    """Unloading the only entry then setting it up again must revive memory.

    `async_setup` runs once per HA run, so nothing else would repopulate the
    registry the unload emptied.
    """
    entry = await _setup(hass, tmp_path_factory, mock_llm_client)
    assert sorted(hass.data[DOMAIN]["memory"].names()) == ["conversations", "entities"]

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.data[DOMAIN]["memory"].names() == []

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert sorted(hass.data[DOMAIN]["memory"].names()) == ["conversations", "entities"]


async def test_only_flagged_stores_receive_conversation_ingest(
    hass: HomeAssistant, mock_llm_client, tmp_path_factory, patched_store
) -> None:
    await _setup(hass, tmp_path_factory, mock_llm_client)
    registry = hass.data[DOMAIN]["memory"]
    targets = registry.stores_for_conversation_ingest()
    assert len(targets) == 1
    assert targets[0] is registry.get("conversations")


async def test_no_memory_block_yields_empty_registry(
    hass: HomeAssistant, mock_llm_client, tmp_path_factory
) -> None:
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text("tools: []\n")
    hass.config.config_dir = str(cdir)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = hass.data[DOMAIN]["memory"]
    assert registry.names() == []


async def test_ingest_fans_out_to_every_flagged_store(hass: HomeAssistant) -> None:
    from custom_components.smartchain.tools.memory.ingest import (
        ingest_conversation_turn,
    )

    a = MagicMock()
    a.is_available = True
    a.add = AsyncMock(return_value=["1"])
    b = MagicMock()
    b.is_available = True
    b.add = AsyncMock(return_value=["2"])

    await ingest_conversation_turn(
        [a, b],
        user_text="q",
        assistant_text="a",
        metadata={"kind": "conversation", "timestamp": "t"},
    )
    a.add.assert_awaited_once()
    b.add.assert_awaited_once()


async def test_ingest_continues_when_one_store_fails(hass: HomeAssistant, caplog) -> None:
    from custom_components.smartchain.tools.memory.ingest import (
        ingest_conversation_turn,
    )

    bad = MagicMock()
    bad.is_available = True
    bad.add = AsyncMock(side_effect=RuntimeError("provider down"))
    good = MagicMock()
    good.is_available = True
    good.add = AsyncMock(return_value=["1"])

    await ingest_conversation_turn(
        [bad, good],
        user_text="q",
        assistant_text="a",
        metadata={"kind": "conversation", "timestamp": "t"},
    )
    good.add.assert_awaited_once()
    assert "memory" in caplog.text.lower()


async def test_ingest_with_no_stores_is_a_noop(hass: HomeAssistant) -> None:
    from custom_components.smartchain.tools.memory.ingest import (
        ingest_conversation_turn,
    )

    await ingest_conversation_turn(
        [], user_text="q", assistant_text="a", metadata={"kind": "conversation"}
    )
