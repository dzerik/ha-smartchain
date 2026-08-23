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


async def test_clear_memory_unknown_store_raises(
    hass: HomeAssistant, tools_dir: Path, patched_store
) -> None:
    """Naming a store that is not configured is an error, not a silent no-op."""
    (tools_dir / "tools.yaml").write_text(
        "tools: []\n"
        "memory:\n"
        "  stores:\n"
        "    - name: conversations\n"
        '      embeddings: "GigaChat Embeddings"\n'
    )
    _add_embeddings_entry(hass)
    await async_setup(hass, {})

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, SERVICE_CLEAR_MEMORY, {"store": "nope"}, blocking=True
        )
