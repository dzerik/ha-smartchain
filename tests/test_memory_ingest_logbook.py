"""Tests for MemoryLogbookPoller."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.config import LogbookConfig
from custom_components.smartchain.tools.memory.ingest import (
    MemoryLogbookPoller,
    _logbook_doc_id,
)


def test_logbook_doc_id_is_stable() -> None:
    a = _logbook_doc_id("2026-05-27T10:00:00+00:00", "light.k", "turned on")
    b = _logbook_doc_id("2026-05-27T10:00:00+00:00", "light.k", "turned on")
    c = _logbook_doc_id("2026-05-27T10:00:00+00:00", "light.k", "turned off")
    assert a == b
    assert a != c


async def test_poller_invokes_logbook_and_adds(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.add = AsyncMock(return_value=["id-1"])

    fake_entries = [
        {
            "when": datetime(2026, 5, 27, 10, 0, tzinfo=UTC),
            "name": "Kitchen light",
            "entity_id": "light.kitchen",
            "message": "turned on",
            "domain": "light",
        }
    ]

    with patch(
        "custom_components.smartchain.tools.memory.ingest._fetch_logbook_entries",
        new_callable=AsyncMock,
        return_value=fake_entries,
    ):
        poller = MemoryLogbookPoller(hass, store, LogbookConfig(enabled=True, domains=["light"]))
        await poller.run_once()

    store.add.assert_awaited_once()
    args, kwargs = store.add.call_args
    assert "Kitchen light" in (args[0] if args else kwargs.get("text", ""))


async def test_poller_advances_watermark(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.add = AsyncMock(return_value=["id-1"])

    ts = datetime(2026, 5, 27, 10, 0, tzinfo=UTC)
    with patch(
        "custom_components.smartchain.tools.memory.ingest._fetch_logbook_entries",
        new_callable=AsyncMock,
        return_value=[
            {
                "when": ts,
                "name": "x",
                "entity_id": "light.k",
                "message": "on",
                "domain": "light",
            }
        ],
    ):
        poller = MemoryLogbookPoller(hass, store, LogbookConfig(enabled=True))
        await poller.run_once()

    assert poller.watermark >= ts


async def test_poller_disabled_does_nothing(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.add = AsyncMock()
    poller = MemoryLogbookPoller(hass, store, LogbookConfig(enabled=False))
    await poller.run_once()
    store.add.assert_not_called()
