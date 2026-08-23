"""The sweep reconciles; it never blindly rebuilds."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.config import EntitySourceConfig
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer
from custom_components.smartchain.tools.memory.store import MemoryStore

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str, name: str = "Name", area: str = "Кухня") -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        area=area,
        device="",
        device_class="",
        aliases=(),
    )


def _store() -> MagicMock:
    """A `MemoryStore` stand-in that only answers to attributes the real class has.

    `spec=MemoryStore` makes a call to a method the store does not actually
    expose (e.g. a since-removed `delete_where`) raise `AttributeError` right
    here, instead of a bare `MagicMock` quietly answering to anything and
    letting the bug reach production.
    """
    store = MagicMock(spec=MemoryStore)
    store.is_available = True
    store.add = AsyncMock(return_value=["id"])
    store.clear = AsyncMock(return_value=1)
    store.list_metadata = AsyncMock(return_value={})
    store.update_metadata = AsyncMock(return_value=True)
    return store


@pytest.fixture
def indexer_factory(request):
    """Build EntityIndexers whose `resolve_candidates` patch is guaranteed to stop.

    Every patcher created through this factory is tracked and stopped at
    teardown, even if a test never touches it and even if a test stops it
    itself mid-run (double-stop is tolerated).
    """
    patchers: list = []

    def _make(hass: HomeAssistant, store, candidates, **cfg) -> EntityIndexer:
        indexer = EntityIndexer(hass, store, EntitySourceConfig(**cfg))
        patcher = patch(
            "custom_components.smartchain.tools.memory.entity_index.resolve_candidates",
            return_value={c.entity_id: c for c in candidates},
        )
        indexer._patcher = patcher  # exposed so a test may stop/swap it early
        patcher.start()
        patchers.append(patcher)
        return indexer

    def _stop_all() -> None:
        for patcher in patchers:
            try:
                patcher.stop()
            except RuntimeError:
                pass  # already stopped by the test itself

    request.addfinalizer(_stop_all)
    return _make


async def test_first_sweep_indexes_everything(hass: HomeAssistant, indexer_factory) -> None:
    store = _store()
    indexer = indexer_factory(hass, store, [_cand("light.a"), _cand("light.b")])

    result = await indexer.reconcile()

    assert result.new == 2
    assert result.changed == 0
    assert store.add.await_count == 2
    assert store.add.await_args_list[0].kwargs["doc_id"] == "entity:light.a"


async def test_second_sweep_of_an_unchanged_home_embeds_nothing(
    hass: HomeAssistant, indexer_factory
) -> None:
    """The central promise: a restart costs zero embeddings."""
    store = _store()
    cands = [_cand("light.a"), _cand("light.b")]
    indexer = indexer_factory(hass, store, cands)

    await indexer.reconcile()
    stored = {call.kwargs["doc_id"]: call.args[1] for call in store.add.await_args_list}
    store.add.reset_mock()
    store.list_metadata = AsyncMock(return_value=stored)

    result = await indexer.reconcile()

    assert store.add.await_count == 0
    assert result.unchanged == 2
    assert result.new == 0


async def test_a_renamed_entity_re_embeds_exactly_one(hass: HomeAssistant, indexer_factory) -> None:
    store = _store()
    indexer = indexer_factory(hass, store, [_cand("light.a"), _cand("light.b")])
    await indexer.reconcile()
    stored = {call.kwargs["doc_id"]: call.args[1] for call in store.add.await_args_list}
    store.add.reset_mock()
    store.list_metadata = AsyncMock(return_value=stored)

    indexer._patcher.stop()
    with patch(
        "custom_components.smartchain.tools.memory.entity_index.resolve_candidates",
        return_value={
            "light.a": _cand("light.a", name="Переименован"),
            "light.b": _cand("light.b"),
        },
    ):
        result = await indexer.reconcile()

    assert store.add.await_count == 1
    assert store.add.await_args.kwargs["doc_id"] == "entity:light.a"
    assert result.changed == 1
    assert result.unchanged == 1


async def test_a_vanished_entity_is_deleted(hass: HomeAssistant, indexer_factory) -> None:
    store = _store()
    store.list_metadata = AsyncMock(
        return_value={
            "entity:light.a": {"kind": "entity", "entity_id": "light.a", "fingerprint": "x"},
            "entity:light.gone": {
                "kind": "entity",
                "entity_id": "light.gone",
                "fingerprint": "y",
            },
        }
    )
    indexer = indexer_factory(hass, store, [_cand("light.a")])

    result = await indexer.reconcile()

    assert result.removed == 1
    store.clear.assert_awaited_once_with({"kind": "entity", "entity_id": "light.gone"})


async def test_a_narrowed_preset_removes_what_dropped_out(
    hass: HomeAssistant, indexer_factory
) -> None:
    store = _store()
    store.list_metadata = AsyncMock(
        return_value={
            f"entity:{eid}": {"kind": "entity", "entity_id": eid, "fingerprint": "x"}
            for eid in ("light.a", "sensor.temp", "update.fw")
        }
    )
    indexer = indexer_factory(hass, store, [_cand("light.a")])

    result = await indexer.reconcile()

    assert result.removed == 2


async def test_full_ignores_fingerprints(hass: HomeAssistant, indexer_factory) -> None:
    """For when the embedding model changed but the catalogue text did not."""
    store = _store()
    indexer = indexer_factory(hass, store, [_cand("light.a")])
    await indexer.reconcile()
    stored = {call.kwargs["doc_id"]: call.args[1] for call in store.add.await_args_list}
    store.add.reset_mock()
    store.list_metadata = AsyncMock(return_value=stored)

    result = await indexer.reconcile(full=True)

    assert store.add.await_count == 1
    assert result.changed == 1


async def test_state_is_indexed_only_when_asked(hass: HomeAssistant, indexer_factory) -> None:
    hass.states.async_set("light.a", "on", {})
    store = _store()

    indexer = indexer_factory(hass, store, [_cand("light.a")], index_states=False)
    await indexer.reconcile()
    assert "state" not in store.add.await_args.args[1]

    store.add.reset_mock()
    indexer._patcher.stop()
    indexer2 = indexer_factory(hass, store, [_cand("light.a")], index_states=True)
    await indexer2.reconcile()
    assert store.add.await_args.args[1]["state"] == "on"


async def test_a_failing_sweep_never_raises(hass: HomeAssistant, caplog, indexer_factory) -> None:
    store = _store()
    store.list_metadata = AsyncMock(side_effect=RuntimeError("boom"))
    indexer = indexer_factory(hass, store, [_cand("light.a")])

    result = await indexer.reconcile()

    assert result.new == 0
    assert "entity index" in caplog.text.lower()
    # The actual claim: the previous index survived untouched.
    store.clear.assert_not_awaited()
    store.add.assert_not_awaited()


async def test_a_failed_write_never_reaches_delete(hass: HomeAssistant, indexer_factory) -> None:
    """Write-before-delete ordering, pinned.

    A failed write followed by a completed delete would leave the store
    worse than before the sweep started; this must never happen.
    """
    store = _store()
    store.list_metadata = AsyncMock(
        return_value={
            "entity:light.gone": {"kind": "entity", "entity_id": "light.gone", "fingerprint": "x"}
        }
    )
    store.add = AsyncMock(side_effect=RuntimeError("boom"))
    indexer = indexer_factory(hass, store, [_cand("light.a")])

    await indexer.reconcile()

    store.clear.assert_not_awaited()


async def test_an_unavailable_store_is_skipped(hass: HomeAssistant, indexer_factory) -> None:
    store = _store()
    store.is_available = False
    indexer = indexer_factory(hass, store, [_cand("light.a")])

    await indexer.reconcile()

    assert store.add.await_count == 0
