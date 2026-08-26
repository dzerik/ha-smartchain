"""What the rest of the integration does when the memory store gives up.

`MemoryStore.add` and `MemoryStore.search` used to absorb every backend and
embeddings failure and answer `[]`. Three callers were written against a
store that raises, and all three were tested against mocks that raise — so
each of these guarantees was green in CI and false in production:

* the `search_memory` tool renders "Memory lookup failed; see logs." instead
  of letting the model announce "No memories matched the query.";
* the logbook poller counts a row `written` only when `add` returned;
* the entity indexer aborts a sweep before it deletes orphans if a write
  failed, so the index is never left worse than it started.

Every store below is a real `MemoryStore` over a backend that answers by
never answering, driven through the same `asyncio.timeout` budget the
production code uses. Nothing here mocks `MemoryStore` itself — that is the
whole point.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import DOMAIN
from custom_components.smartchain.tools.memory.config import EntitySourceConfig, LogbookConfig
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer, SweepResult
from custom_components.smartchain.tools.memory.ingest import MemoryLogbookPoller
from custom_components.smartchain.tools.memory.search_tool import execute_memory_search
from custom_components.smartchain.tools.memory.store import MemoryStore
from tests.test_memory_timeouts import BUDGET, STORE_BUDGET, WedgedBackend, _embeddings

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
async def wedged_store(hass: HomeAssistant):
    store = MemoryStore(hass, _embeddings(), WedgedBackend())
    await store.async_setup()
    assert store.is_available is True
    return store


def _registry(store) -> MagicMock:
    reg = MagicMock()
    reg.names.return_value = ["only"]
    reg.describe.return_value = [("only", "")]
    reg.__len__.return_value = 1
    reg.get.side_effect = lambda name=None: store
    return reg


async def test_a_wedged_store_is_reported_as_a_failure_not_as_no_memories(
    hass: HomeAssistant, wedged_store
) -> None:
    """The sentence the model gets back is the whole guarantee.

    "No memories matched the query." is an answer about the home. "Memory
    lookup failed" is an answer about the software. A store that timed out
    has said nothing about the home, and must not be quoted as if it had.
    """
    hass.data.setdefault(DOMAIN, {})["memory"] = _registry(wedged_store)

    with patch(STORE_BUDGET, BUDGET):
        result = await execute_memory_search(hass, query="what did I say yesterday")

    assert "lookup failed" in result.lower()
    assert "no memories matched" not in result.lower()


async def test_the_logbook_poller_does_not_count_rows_it_failed_to_write(
    hass: HomeAssistant, wedged_store
) -> None:
    """`written` is the number of rows in the store, not the number attempted."""
    entries = [
        {
            "when": datetime(2026, 5, 27, 10, 0, tzinfo=UTC),
            "name": "Kitchen light",
            "entity_id": "light.kitchen",
            "message": "turned on",
            "domain": "light",
        }
    ]

    with (
        patch(
            "custom_components.smartchain.tools.memory.ingest._fetch_logbook_entries",
            new_callable=AsyncMock,
            return_value=entries,
        ),
        patch(STORE_BUDGET, BUDGET),
    ):
        poller = MemoryLogbookPoller(
            hass, wedged_store, LogbookConfig(enabled=True, domains=["light"])
        )
        written = await poller.run_once()

    assert written == 0


async def test_a_sweep_that_cannot_write_deletes_nothing(hass: HomeAssistant, wedged_store) -> None:
    """Write-before-delete, against a real store rather than a mock.

    `list_metadata` is the one method allowed to answer here, so the sweep
    gets far enough to have an orphan to delete; the write underneath it
    never lands. Had `add` gone on returning `[]`, the sweep would have
    sailed past the failed write and deleted `light.gone` — leaving the
    index missing both the entity it could not write and the one it removed.
    """
    stored = {
        "entity:light.gone": {"kind": "entity", "entity_id": "light.gone", "fingerprint": "x"}
    }
    wedged_store.backend.list_metadata = AsyncMock(return_value=stored)
    delete_where = AsyncMock(return_value=1)
    wedged_store.backend.delete_where = delete_where

    candidate = EntityCandidate(
        entity_id="light.a",
        domain="light",
        name="A",
        area="Кухня",
        device="",
        device_class="",
        aliases=(),
    )
    indexer = EntityIndexer(hass, wedged_store, EntitySourceConfig())

    with (
        patch(
            "custom_components.smartchain.tools.memory.entity_index.resolve_candidates",
            return_value={candidate.entity_id: candidate},
        ),
        patch(STORE_BUDGET, BUDGET),
    ):
        result = await indexer.reconcile()

    delete_where.assert_not_awaited()
    assert result == SweepResult()
