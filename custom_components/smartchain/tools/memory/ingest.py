"""Memory ingestion: conversation turns + logbook entries."""

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .config import LogbookConfig
from .store import MemoryStore

LOGGER = logging.getLogger(__name__)


async def ingest_conversation_turn(
    store: MemoryStore,
    user_text: str,
    assistant_text: str,
    metadata: dict[str, Any],
) -> None:
    """Embed and persist a single user+assistant exchange.

    Failures are logged at WARNING and never propagated — ingestion must not
    affect the user-facing conversation response.
    """
    if not store.is_available:
        return
    if not assistant_text:
        return

    combined = f"User: {user_text or ''}\n\nAssistant: {assistant_text}"
    try:
        await store.add(combined, metadata)
    except Exception:  # noqa: BLE001
        LOGGER.warning("smartchain memory ingest failed", exc_info=True)


def _logbook_doc_id(timestamp_iso: str, entity_id: str, message: str) -> str:
    """Stable id so re-polling the same window does not duplicate rows."""
    raw = f"{timestamp_iso}|{entity_id}|{message}".encode()
    return "logbook_" + hashlib.sha1(raw).hexdigest()  # noqa: S324


async def _fetch_logbook_entries(
    hass: HomeAssistant,
    start: datetime,
    end: datetime,
    domains: list[str],
) -> list[dict]:
    """Read HA logbook entries between `start` and `end`, filtered by domain.

    Returns dicts shaped {when, name, entity_id, message, domain}. Wrapped here
    so tests can patch this single function rather than HA internals.

    Uses ``logbook.humanify`` + ``logbook._get_events`` which are HA internals.
    If those names are absent in the installed HA version (they were renamed /
    removed in HA 2024+), the function returns [] and logs a debug message so
    that the rest of the memory subsystem is unaffected.
    """
    try:
        from homeassistant.components import logbook
    except ImportError:
        LOGGER.debug("homeassistant.components.logbook not available; skipping logbook ingest")
        return []

    def _query() -> list[dict]:
        try:
            get_events = logbook._get_events  # noqa: SLF001
            humanify = logbook.humanify
        except AttributeError:
            LOGGER.debug(
                "logbook._get_events / logbook.humanify not found in this HA version; "
                "logbook ingest will return no entries"
            )
            return []

        items: list[dict] = []
        try:
            raw_events = list(
                get_events(
                    hass,
                    start,
                    end,
                    entity_ids=None,
                    device_ids=None,
                    filters=None,
                )
            )
            for raw in humanify(hass, raw_events, None, None):
                if domains and raw.get("domain") not in domains:
                    continue
                when = raw.get("when")
                if when is None:
                    continue
                items.append(
                    {
                        "when": (
                            when
                            if isinstance(when, datetime)
                            else dt_util.parse_datetime(str(when))
                        ),
                        "name": raw.get("name", ""),
                        "entity_id": raw.get("entity_id", ""),
                        "message": raw.get("message", ""),
                        "domain": raw.get("domain", ""),
                    }
                )
        except Exception:  # noqa: BLE001
            LOGGER.debug("logbook ingest query failed", exc_info=True)
        return items

    return await hass.async_add_executor_job(_query)


class MemoryLogbookPoller:
    """Periodic poller that reads HA logbook and writes embeddings."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: MemoryStore,
        config: LogbookConfig,
    ) -> None:
        self.hass = hass
        self.store = store
        self.config = config
        self.watermark: datetime = dt_util.utcnow()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def run_once(self) -> int:
        """One iteration: fetch entries since watermark, embed, advance watermark."""
        if not self.config.enabled or not self.store.is_available:
            return 0
        start = self.watermark
        end = dt_util.utcnow()
        if end <= start:
            return 0
        entries = await _fetch_logbook_entries(self.hass, start, end, self.config.domains)
        written = 0
        latest = start
        for entry in entries:
            when = entry["when"]
            if when is None:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            ts_iso = when.isoformat()
            text = f"{ts_iso} • {entry['name']} ({entry['entity_id']}): {entry['message']}"
            doc_id = _logbook_doc_id(ts_iso, entry["entity_id"], entry["message"])
            try:
                await self.store.add(
                    text,
                    {
                        "kind": "logbook",
                        "timestamp": ts_iso,
                        "entity_id": entry["entity_id"],
                        "domain": entry["domain"],
                    },
                    doc_id=doc_id,
                )
                written += 1
            except Exception:  # noqa: BLE001
                LOGGER.warning(
                    "logbook ingest failed for %s",
                    entry["entity_id"],
                    exc_info=True,
                )
            if when > latest:
                latest = when
        self.watermark = latest
        return written

    def start(self) -> None:
        if self._task is not None or not self.config.enabled:
            return
        self._task = self.hass.async_create_background_task(
            self._loop(), name="smartchain_memory_logbook"
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
        interval = self.config.poll_interval_minutes * 60
        while not self._stop.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001
                LOGGER.exception("logbook poller iteration failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                return
