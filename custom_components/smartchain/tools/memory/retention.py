"""Daily retention cleanup task."""

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .store import MemoryStore

LOGGER = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86400


def compute_cutoff(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


class RetentionTask:
    """Runs once a day, deletes memory entries older than `days`."""

    def __init__(self, hass: HomeAssistant, store: MemoryStore, days: int) -> None:
        self.hass = hass
        self.store = store
        self.days = days
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def is_enabled(self) -> bool:
        return self.days > 0

    async def run_once(self) -> int:
        if not self.is_enabled or not self.store.is_available:
            return 0
        cutoff = compute_cutoff(dt_util.utcnow(), self.days)
        try:
            return await self.store.delete_older_than(cutoff)
        except Exception:  # noqa: BLE001
            LOGGER.exception("memory retention cleanup failed")
            return 0

    def start(self) -> None:
        if self._task is not None or not self.is_enabled:
            return
        # stop() latches the event, so a restarted task would fall straight
        # out of `_loop`'s while and never sweep again — alive-looking and
        # silently doing nothing. Clear the latch before spawning.
        self._stop.clear()
        self._task = self.hass.async_create_background_task(
            self._loop(), name="smartchain_memory_retention"
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                return
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_SECONDS_PER_DAY)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                return
