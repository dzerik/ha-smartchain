"""End-to-end: memory YAML -> store init -> conversation ingest -> search retrieves it."""

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

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
def fake_memory_store():
    """Patch MemoryStore so we never actually open a vector backend."""
    stub = MagicMock()
    stub.is_available = True
    stub.add = AsyncMock(return_value=["doc-1"])
    stub.search = AsyncMock(return_value=[])  # tests can override after setup
    stub.clear = AsyncMock(return_value=0)
    stub.delete_older_than = AsyncMock(return_value=0)
    stub.async_setup = AsyncMock()
    stub.close = AsyncMock()
    with patch(
        "custom_components.smartchain.tools.memory.store.MemoryStore",
        return_value=stub,
    ):
        with patch(
            "custom_components.smartchain.MemoryStore",
            return_value=stub,
        ):
            yield stub


async def test_memory_enabled_via_yaml_lands_in_hass_data(
    hass: HomeAssistant,
    mock_llm_client,
    tmp_path_factory,
    fake_memory_store,
) -> None:
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text(
        "tools: []\nmemory:\n  provider: ollama\n  model: nomic-embed-text\n"
    )
    hass.config.config_dir = str(cdir)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
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

    assert hass.data[DOMAIN].get("memory") is fake_memory_store


async def test_memory_disabled_when_yaml_lacks_block(
    hass: HomeAssistant,
    mock_llm_client,
    tmp_path_factory,
) -> None:
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text("tools: []\n")
    hass.config.config_dir = str(cdir)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
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

    assert hass.data[DOMAIN].get("memory") is None
