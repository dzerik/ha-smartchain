"""Tests for the daily retention cleanup."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.retention import (
    RetentionTask,
    compute_cutoff,
)


def test_compute_cutoff() -> None:
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    cutoff = compute_cutoff(now, days=30)
    assert cutoff == now - timedelta(days=30)


def test_retention_disabled_when_days_zero() -> None:
    task = RetentionTask(MagicMock(), MagicMock(), days=0)
    assert task.is_enabled is False


async def test_retention_run_once_calls_store(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.delete_older_than = AsyncMock(return_value=7)
    task = RetentionTask(hass, store, days=10)
    deleted = await task.run_once()
    assert deleted == 7
    store.delete_older_than.assert_awaited_once()


async def test_retention_run_once_noop_when_disabled(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.delete_older_than = AsyncMock()
    task = RetentionTask(hass, store, days=0)
    deleted = await task.run_once()
    assert deleted == 0
    store.delete_older_than.assert_not_called()
