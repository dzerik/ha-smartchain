"""Memory ingestion: conversation turns + (Task 9) logbook entries."""

import logging
from typing import Any

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
