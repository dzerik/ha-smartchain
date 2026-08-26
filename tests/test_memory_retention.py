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


def test_cancellederror_is_not_an_exception() -> None:
    """The language fact the `stop()` handler is built on.

    Since Python 3.8 `asyncio.CancelledError` inherits straight from
    `BaseException`, so `except Exception` does *not* catch it. Every test
    below that pins the tuple in `RetentionTask.stop()` rests on this; if a
    future Python moved it back under `Exception` the tuple would become
    genuinely redundant and this test would say so first.
    """
    assert asyncio.CancelledError.__mro__ == (asyncio.CancelledError, BaseException, object)
    assert not issubclass(asyncio.CancelledError, Exception)


async def test_stop_swallows_cancellederror_from_the_cancelled_task(
    hass: HomeAssistant,
) -> None:
    """`stop()` cancels its own task, so awaiting it may raise CancelledError.

    That exception must never leave `stop()`: `MemoryRegistry.shutdown()`
    stops every retention task in one sequential loop, and a CancelledError
    escaping the first one aborts the whole shutdown — later pollers keep
    running and stores are never closed.

    This is the test that dies if anyone "simplifies" the handler's tuple to
    a bare `except Exception`, which cannot catch a BaseException subclass.
    """
    store = FakeStore()
    task = RetentionTask(hass, store, days=30)
    running = asyncio.Event()

    async def loop_that_lets_cancellation_through() -> None:
        running.set()
        # A bare sleep has no CancelledError handler, so the cancellation
        # propagates out of the task exactly as an unguarded await would.
        await asyncio.sleep(3600)

    with patch.object(task, "_loop", loop_that_lets_cancellation_through):
        task.start()
        # Bounded: if a regression stops the loop from running at all, this
        # test must fail rather than hang the whole suite.
        async with asyncio.timeout(5):
            await running.wait()
        await task.stop()

    assert task._task is None


async def test_start_sweeps_eagerly_and_stops_clean(hass: HomeAssistant) -> None:
    """`start()` sweeps synchronously, and an instant `stop()` stays quiet.

    There is deliberately no `await` between the two — a config-entry unload
    straight after setup looks exactly like this. Two things are pinned:
    `hass.async_create_background_task` starts the coroutine *eagerly*, so
    the first sweep has already reached the store before `start()` returns;
    and `stop()` then completes without raising.

    Note for whoever runs mutation checks: this test does *not* die on the
    `except (asyncio.CancelledError, Exception)` -> `except Exception`
    mutation. Because the task starts eagerly it is suspended inside
    `_loop`'s own guarded `wait_for`, so `_loop` absorbs the cancellation and
    `stop()` never sees it. The test that does die is
    `test_stop_swallows_cancellederror_from_the_cancelled_task` above.
    """
    store = FakeStore({"ancient": FROZEN - timedelta(days=400)})
    task = RetentionTask(hass, store, days=30)

    task.start()
    assert len(store.cutoffs) == 1, "the background task did not start eagerly"

    await task.stop()

    assert task._task is None


async def test_loop_absorbs_cancellation_while_waiting_between_sweeps(
    hass: HomeAssistant,
) -> None:
    """`_loop` ends itself on cancellation instead of dying of it.

    The task spends almost all its life parked in `wait_for`, so this is
    where a shutdown cancellation lands. `_loop` catches it and returns, and
    the assertion is on the *task state*: FINISHED, not CANCELLED.

    That distinction is the whole point. `stop()` would swallow a
    CancelledError anyway, so testing only "stop() was quiet" lets the
    handler inside `_loop` rot away unnoticed. The two layers are deliberate
    belt-and-braces; neither is allowed to become the single thing standing
    between a cancellation and `MemoryRegistry.shutdown()`.
    """
    store = FakeStore()
    task = RetentionTask(hass, store, days=30)

    with patch.object(retention_module, "_SECONDS_PER_DAY", 3600):
        task.start()
        await asyncio.sleep(0.02)
        raw = task._task
        assert raw is not None
        await task.stop()

    assert raw.done()
    assert not raw.cancelled(), "_loop let the cancellation kill the task"


async def test_loop_absorbs_cancellation_landing_mid_sweep(hass: HomeAssistant) -> None:
    """The same contract at the other await point: inside `delete_older_than`.

    A slow backend means a shutdown can arrive while the sweep is still in
    flight. `run_once` guards only `Exception`, so the cancellation travels
    up to `_loop`, which must end the loop cleanly rather than let the task
    finish in the CANCELLED state.
    """
    store = FakeStore()
    reached_backend = asyncio.Event()
    never = asyncio.Event()

    async def hang_in_the_backend(cutoff: datetime) -> int:
        store.cutoffs.append(cutoff)
        reached_backend.set()
        await never.wait()
        return 0

    store.delete_older_than = hang_in_the_backend  # type: ignore[method-assign]
    task = RetentionTask(hass, store, days=30)

    task.start()
    # Bounded: a regression that never reaches the backend must fail here,
    # not park the suite on an event nobody will ever set.
    async with asyncio.timeout(5):
        await reached_backend.wait()
    raw = task._task
    assert raw is not None
    await task.stop()

    assert raw.done()
    assert not raw.cancelled(), "_loop let the cancellation kill the task mid-sweep"


async def test_stop_is_safe_to_call_twice(hass: HomeAssistant) -> None:
    """Shutdown paths can overlap; the second `stop()` must stay quiet."""
    store = FakeStore()
    task = RetentionTask(hass, store, days=30)

    with patch.object(retention_module, "_SECONDS_PER_DAY", 3600):
        task.start()
        await asyncio.sleep(0.02)
        await task.stop()
        await task.stop()

    assert task._task is None


async def test_run_once_does_not_swallow_cancellation(hass: HomeAssistant) -> None:
    """Only `Exception` is a backend failure — a cancellation must fly on.

    If the guard around `delete_older_than` widened to `BaseException`, a
    shutdown arriving mid-sweep would be logged as "cleanup failed",
    reported as zero deletions and then swallowed, leaving `_loop` to go
    straight back to sleep instead of exiting.
    """
    store = FakeStore()

    async def cancel_mid_delete(cutoff: datetime) -> int:
        store.cutoffs.append(cutoff)
        raise asyncio.CancelledError

    store.delete_older_than = cancel_mid_delete  # type: ignore[method-assign]
    task = RetentionTask(hass, store, days=30)

    with pytest.raises(asyncio.CancelledError):
        await task.run_once()

    assert store.cutoffs, "the sweep never reached the store"


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
