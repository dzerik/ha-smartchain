"""Tests for the smartchain.clear_memory service."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.smartchain import async_setup
from custom_components.smartchain.const import (
    DOMAIN,
    EVENT_MEMORY_CLEARED,
    SERVICE_CLEAR_MEMORY,
)


@pytest.fixture
def tools_dir(hass: HomeAssistant, tmp_path_factory) -> Path:
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    hass.config.config_dir = str(cdir)
    return cdir / "smartchain"


async def test_clear_memory_without_config_raises(hass: HomeAssistant, tools_dir: Path) -> None:
    """When no memory: block in YAML, the service raises HomeAssistantError."""
    (tools_dir / "tools.yaml").write_text("tools: []\n")
    await async_setup(hass, {})
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, SERVICE_CLEAR_MEMORY, {}, blocking=True)


async def test_clear_memory_fires_event(hass: HomeAssistant, tools_dir: Path, monkeypatch) -> None:
    """When memory is configured, clear fires EVENT_MEMORY_CLEARED with deleted count."""
    (tools_dir / "tools.yaml").write_text(
        "tools: []\nmemory:\n  provider: ollama\n  model: nomic-embed-text\n"
    )

    # Patch MemoryStore so we don't actually open Chroma in the test.
    from custom_components.smartchain.tools.memory import store as store_mod

    class _StubStore:
        is_available = True
        clear = AsyncMock(return_value=4)

    monkeypatch.setattr(store_mod, "MemoryStore", lambda *a, **kw: _StubStore())

    await async_setup(hass, {})

    events: list = []
    hass.bus.async_listen(EVENT_MEMORY_CLEARED, lambda e: events.append(e))

    await hass.services.async_call(
        DOMAIN, SERVICE_CLEAR_MEMORY, {"kind": "conversation"}, blocking=True
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["deleted"] == 4
