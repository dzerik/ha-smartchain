"""Tests for the daily retention cleanup.

This is the only code in the integration that deletes user data
irreversibly, so the assertions here name the exact cutoff instant rather
than the fact that a call happened: a task that deletes everything older
than one day satisfies "delete_older_than was awaited" just as well as one
that honours the configured window.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory import retention as retention_module
from custom_components.smartchain.tools.memory.retention import (
    RetentionTask,
    compute_cutoff,
)

FROZEN = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


class FakeStore:
    """A store that really holds dated rows and really drops the old ones.

    Asserting against surviving rows keeps the retention tests honest: a
    wrong cutoff shows up as data that vanished, not as a mock call that
    looked plausible.
    """

    def __init__(self, rows: dict[str, datetime] | None = None) -> None:
        self.is_available = True
        self.rows: dict[str, datetime] = dict(rows or {})
        self.cutoffs: list[datetime] = []
        self.fail_times = 0

    async def delete_older_than(self, cutoff: datetime) -> int:
        self.cutoffs.append(cutoff)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("backend unreachable")
        doomed = [key for key, stamp in self.rows.items() if stamp < cutoff]
        for key in doomed:
            del self.rows[key]
        return len(doomed)


def test_compute_cutoff() -> None:
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    cutoff = compute_cutoff(now, days=30)
    assert cutoff == now - timedelta(days=30)


def test_compute_cutoff_scales_with_days() -> None:
    now = datetime(2026, 5, 27, 12, 0, tzinfo=UTC)
    assert compute_cutoff(now, days=1) != compute_cutoff(now, days=30)


def test_retention_disabled_when_days_zero() -> None:
    task = RetentionTask(MagicMock(), MagicMock(), days=0)
    assert task.is_enabled is False


@pytest.mark.parametrize("days", [1, 7, 30, 90, 3650])
async def test_run_once_uses_the_configured_window(hass: HomeAssistant, days: int) -> None:
    """The cutoff is `now - days`, for the configured days and no other."""
    store = MagicMock()
    store.is_available = True
    store.delete_older_than = AsyncMock(return_value=7)
    task = RetentionTask(hass, store, days=days)

    with freeze_time(FROZEN):
        deleted = await task.run_once()

    assert deleted == 7
    store.delete_older_than.assert_awaited_once_with(FROZEN - timedelta(days=days))


async def test_run_once_keeps_everything_newer_than_the_window(hass: HomeAssistant) -> None:
    """A 30-day window must not touch a 29-day-old row."""
    store = FakeStore(
        {
            "today": FROZEN - timedelta(hours=1),
            "day_old": FROZEN - timedelta(days=1),
            "just_inside": FROZEN - timedelta(days=29, hours=23),
            "just_outside": FROZEN - timedelta(days=30, hours=1),
            "ancient": FROZEN - timedelta(days=400),
        }
    )
    task = RetentionTask(hass, store, days=30)

    with freeze_time(FROZEN):
        deleted = await task.run_once()

    assert deleted == 2
    assert sorted(store.rows) == ["day_old", "just_inside", "today"]


async def test_run_once_noop_when_disabled(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.delete_older_than = AsyncMock()
    task = RetentionTask(hass, store, days=0)
    deleted = await task.run_once()
    assert deleted == 0
    store.delete_older_than.assert_not_called()


@pytest.mark.parametrize("days", [-1, -30, -3650])
async def test_negative_days_deletes_nothing(hass: HomeAssistant, days: int) -> None:
    """A negative window would put the cutoff in the future — i.e. delete all."""
    store = FakeStore({"today": FROZEN, "ancient": FROZEN - timedelta(days=400)})
    task = RetentionTask(hass, store, days=days)

    assert task.is_enabled is False
    with freeze_time(FROZEN):
        assert await task.run_once() == 0

    assert store.cutoffs == []
    assert sorted(store.rows) == ["ancient", "today"]


async def test_run_once_noop_when_store_unavailable(hass: HomeAssistant) -> None:
    store = FakeStore({"ancient": FROZEN - timedelta(days=400)})
    store.is_available = False
    task = RetentionTask(hass, store, days=30)

    assert await task.run_once() == 0
    assert store.cutoffs == []
    assert sorted(store.rows) == ["ancient"]


async def test_delete_failure_is_reported_and_deletes_nothing(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A failing backend returns 0 — but loudly, with the traceback."""
    store = FakeStore({"ancient": FROZEN - timedelta(days=400)})
    store.fail_times = 1
    task = RetentionTask(hass, store, days=30)

    with caplog.at_level(logging.ERROR, logger=retention_module.LOGGER.name):
        assert await task.run_once() == 0

    assert sorted(store.rows) == ["ancient"]
    assert "memory retention cleanup failed" in caplog.text
    assert "RuntimeError" in caplog.text


async def test_failed_cycle_is_retried_on_the_next_one(hass: HomeAssistant) -> None:
    """A failed sweep must not leave the old rows behind for good."""
    store = FakeStore({"ancient": FROZEN - timedelta(days=400)})
    store.fail_times = 1
    task = RetentionTask(hass, store, days=30)

    with freeze_time(FROZEN):
        assert await task.run_once() == 0
    assert sorted(store.rows) == ["ancient"]

    later = FROZEN + timedelta(days=1)
    with freeze_time(later):
        assert await task.run_once() == 1

    assert store.rows == {}
    assert store.cutoffs == [FROZEN - timedelta(days=30), later - timedelta(days=30)]


async def test_start_does_nothing_when_disabled(hass: HomeAssistant) -> None:
    store = FakeStore()
    task = RetentionTask(hass, store, days=0)
    task.start()
    assert task._task is None
    await asyncio.sleep(0)
    assert store.cutoffs == []


async def test_start_is_idempotent(hass: HomeAssistant) -> None:
    store = FakeStore()
    task = RetentionTask(hass, store, days=30)
    with patch.object(retention_module, "_SECONDS_PER_DAY", 3600):
        task.start()
        first = task._task
        task.start()
        assert task._task is first
        await asyncio.sleep(0.02)
        await task.stop()
    assert len(store.cutoffs) == 1


async def test_loop_waits_a_full_day_between_sweeps(hass: HomeAssistant) -> None:
    """The period is a day — not a minute, and not zero."""
    store = FakeStore()
    task = RetentionTask(hass, store, days=30)
    timeouts: list[float] = []
    real_wait_for = asyncio.wait_for

    async def spy(awaitable, timeout=None):  # type: ignore[no-untyped-def]
        if timeout is not None and timeout > 1:
            timeouts.append(timeout)
            timeout = 0.01
        return await real_wait_for(awaitable, timeout)

    with patch.object(asyncio, "wait_for", spy):
        task.start()
        await asyncio.sleep(0.05)
        await task.stop()

    assert len(store.cutoffs) >= 2, "the sweep did not repeat"
    assert timeouts, "the loop never waited between sweeps"
    assert set(timeouts) == {86400.0}


async def test_loop_survives_a_failing_sweep(hass: HomeAssistant) -> None:
    """One backend error must not kill the daily task for good."""
    store = FakeStore({"ancient": FROZEN - timedelta(days=400)})
    store.fail_times = 1
    task = RetentionTask(hass, store, days=30)

    with patch.object(retention_module, "_SECONDS_PER_DAY", 0.01):
        task.start()
        await asyncio.sleep(0.05)
        await task.stop()

    assert len(store.cutoffs) >= 2
    assert store.rows == {}


async def test_start_after_stop_resumes_sweeping(hass: HomeAssistant) -> None:
    """A restarted task must actually sweep again, not idle silently."""
    store = FakeStore({"ancient": FROZEN - timedelta(days=400)})
    task = RetentionTask(hass, store, days=30)

    with patch.object(retention_module, "_SECONDS_PER_DAY", 3600):
        task.start()
        await asyncio.sleep(0.02)
        await task.stop()
        assert len(store.cutoffs) == 1

        store.rows["ancient"] = FROZEN - timedelta(days=400)
        task.start()
        assert task._task is not None
        await asyncio.sleep(0.02)
        await task.stop()

    assert len(store.cutoffs) == 2
    assert store.rows == {}
