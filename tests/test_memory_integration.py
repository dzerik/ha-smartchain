"""End-to-end: memory YAML -> registry in hass.data."""

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

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

_YAML_WITH_STORE = """
tools: []
memory:
  stores:
    - name: conversations
      embeddings: "GigaChat Embeddings"
"""


@pytest.fixture
def fake_memory_store():
    """Patch the registry's collaborators so no real backend is opened."""

    def _factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
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
        yield


async def _setup(hass: HomeAssistant, tmp_path_factory, mock_llm_client, yaml: str):
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text(yaml)
    hass.config.config_dir = str(cdir)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
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


async def test_memory_enabled_via_yaml_lands_in_registry(
    hass: HomeAssistant, mock_llm_client, tmp_path_factory, fake_memory_store
) -> None:
    await _setup(hass, tmp_path_factory, mock_llm_client, _YAML_WITH_STORE)
    registry = hass.data[DOMAIN]["memory"]
    assert registry.names() == ["conversations"]


async def test_memory_disabled_when_yaml_lacks_block(
    hass: HomeAssistant, mock_llm_client, tmp_path_factory
) -> None:
    await _setup(hass, tmp_path_factory, mock_llm_client, "tools: []\n")
    registry = hass.data[DOMAIN]["memory"]
    assert registry.names() == []
