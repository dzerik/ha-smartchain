"""Two rebuild paths for one subentry write: one that raced, one that was missing.

`hass.config_entries.async_add_subentry` is `_async_update_entry`, which fires
every update listener as a *background task*. So a panel save used to start two
rebuilds of the shared subsystems at once — the one the websocket handler
awaits, and the one `update_listener` reaches through `async_reload` — with
nothing serialising them. Meanwhile Home Assistant's own subentry dialogs, which
write the same subentries, started no rebuild at all: on a single-entry install
they appeared to work because unloading the last entry sets `subsystems_stopped`
and the next setup rebuilds, and with a second entry configured that accident
stops happening.

The two halves of this file are the two halves of that defect.
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_ANTHROPIC,
    ID_OPENAI,
    SUBENTRY_TYPE_EMBEDDINGS,
    SUBENTRY_TYPE_MEMORY_STORE,
    SUBENTRY_TYPE_TOOL,
    UNIQUE_ID_ANTHROPIC,
    UNIQUE_ID_OPENAI,
)
from custom_components.smartchain.tools.memory import entity_context
from custom_components.smartchain.tools.memory import registry as registry_module

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

EMBEDDINGS_TITLE = "OpenAI Embeddings"


@pytest.fixture
def patched_store():
    """No real backend and no real embeddings provider, so a rebuild does not
    try to reach a database — the same stand-in tests/test_ws_stores.py uses."""

    def _factory(hass, embeddings, backend):
        store = MagicMock()
        store.is_available = True
        store.unavailable_reason = None
        store.async_setup = AsyncMock()
        store.close = AsyncMock()
        return store

    with (
        patch.object(registry_module, "MemoryStore", side_effect=_factory),
        patch.object(registry_module, "create_embeddings_from_subentry", return_value=MagicMock()),
    ):
        yield


def _embeddings_subentry() -> ConfigSubentryData:
    return ConfigSubentryData(
        data={"model": "text-embedding-3-small"},
        subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
        title=EMBEDDINGS_TITLE,
        unique_id=None,
    )


async def _install(hass: HomeAssistant, tmp_path, *, second_entry: bool, subentries=()):
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        options={},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        minor_version=4,
        subentries_data=list(subentries),
    )
    entry.add_to_hass(hass)
    if second_entry:
        MockConfigEntry(
            domain=DOMAIN,
            data={CONF_ENGINE: ID_ANTHROPIC, CONF_API_KEY: "k2"},
            options={},
            unique_id=UNIQUE_ID_ANTHROPIC,
            title=UNIQUE_ID_ANTHROPIC,
            minor_version=4,
        ).add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return entry


class _RebuildWatcher:
    """Records every MemoryRegistry a rebuild builds, every one it shuts down,
    and how many rebuild passes were inside the critical section at once."""

    def __init__(self) -> None:
        self.built: list[object] = []
        self.shut: list[object] = []
        self.inside = 0
        self.max_inside = 0
        self.passes = 0
        # Set once a pass has parked inside build; read to prove a *second*
        # pass was waiting rather than simply never scheduled.
        self.parked = asyncio.Event()
        self.entered_while_parked: int | None = None


@contextlib.contextmanager
def _watch(watcher: _RebuildWatcher, *, park: float = 0.0):
    """Patch the rebuild so passes are observable, and slow at the swap.

    `park` holds the first pass inside the `old_memory.shutdown()` that sits
    between "read the installed registry" and "install the new one" — the exact
    window that made the race destructive, and a window a real shutdown does
    occupy: it stops the retention, logbook-poll and entity-index tasks and
    closes every backend. A second pass arriving inside it reads the *same*
    old registry, so the two shut down one registry twice and the first new one
    is installed over and never shut down at all.

    A plain `sleep`, never a barrier: if the rebuild is correctly serialised no
    second pass can arrive to release a barrier, and the suite would hang
    instead of failing.
    """
    from custom_components import smartchain

    real_build = registry_module.MemoryRegistry.build
    real_shutdown = registry_module.MemoryRegistry.shutdown
    real_rebuild = smartchain._rebuild_subsystems

    async def build(self, *args, **kwargs):
        watcher.built.append(self)
        return await real_build(self, *args, **kwargs)

    async def shutdown(self):
        watcher.shut.append(self)
        # Only inside a rebuild, and only the first one: an unload shuts the
        # registry down too, and that call is not the window under test.
        if park and watcher.inside and not watcher.parked.is_set():
            watcher.parked.set()
            await asyncio.sleep(park)
            watcher.entered_while_parked = watcher.passes
        return await real_shutdown(self)

    async def rebuild(hass):
        watcher.passes += 1
        watcher.inside += 1
        watcher.max_inside = max(watcher.max_inside, watcher.inside)
        try:
            return await real_rebuild(hass)
        finally:
            watcher.inside -= 1

    with (
        patch.object(registry_module.MemoryRegistry, "build", build),
        patch.object(registry_module.MemoryRegistry, "shutdown", shutdown),
        patch.object(smartchain, "_rebuild_subsystems", rebuild),
    ):
        yield


def _assert_memory_survived(hass: HomeAssistant, watcher: _RebuildWatcher) -> None:
    """The registry in `hass.data` is live, and nothing it replaced is still running.

    The second half is the part that used to fail. Two interleaved passes both
    read `hass.data[DOMAIN]["memory"]` before either wrote it, so both shut down
    the *same* old registry and the first new one was orphaned — never shut
    down, its retention, logbook-poll and entity-index tasks still firing for
    the life of the process, against the same backend file the live registry had
    just opened, ingesting every conversation turn twice.
    """
    live = hass.data[DOMAIN]["memory"]
    assert live.names() == ["conversations"], "the installed memory registry is dead"
    orphans = [reg for reg in watcher.built if reg is not live and reg not in watcher.shut]
    assert not orphans, f"{len(orphans)} replaced memory registr(y/ies) left running"


def _store_payload() -> dict:
    return {
        "name": "conversations",
        "embeddings": EMBEDDINGS_TITLE,
        "description": "Dialogue history",
        "backend_type": "sqlite_numpy",
        "source_type": "none",
        "retention_days": 90,
        "ingest_conversation": True,
    }


# --- the racy path --------------------------------------------------------


async def test_a_panel_save_runs_one_rebuild_at_a_time(
    hass: HomeAssistant, hass_ws_client, tmp_path, patched_store
) -> None:
    """One `smartchain/store/save` starts two rebuilds; they must not overlap.

    The websocket handler awaits its own rebuild, and the `async_add_subentry`
    inside it has already scheduled `update_listener` as a background task,
    which reloads the entry and rebuilds again. Both were in flight together.

    The first pass is held at the moment it swaps the memory registry, long
    enough for the second to catch up — the window that made the race
    destructive rather than merely wasteful.
    """
    del patched_store
    entry = await _install(hass, tmp_path, second_entry=False, subentries=[_embeddings_subentry()])
    client = await hass_ws_client(hass)

    watcher = _RebuildWatcher()
    with _watch(watcher, park=0.2):
        await client.send_json_auto_id(
            {
                "type": "smartchain/store/save",
                "entry_id": entry.entry_id,
                "data": _store_payload(),
            }
        )
        msg = await client.receive_json()
        assert msg["success"], msg
        assert msg["result"]["reload_error"] is None
        await hass.async_block_till_done()

    # The lock has to be *contended*, or this test proves nothing: more than
    # one pass ran, and while the first was parked mid-build no other was
    # inside the critical section with it.
    assert watcher.passes >= 2, "only one rebuild ran; this save no longer races"
    assert watcher.parked.is_set()
    assert watcher.entered_while_parked == 1, "a second rebuild entered mid-swap"
    assert watcher.max_inside == 1
    _assert_memory_survived(hass, watcher)


async def test_two_rebuilds_started_together_do_not_interleave(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    """The same claim without Home Assistant's scheduling in the way.

    `_reload_registry` is reachable from the websocket handlers, the update
    listener, entry setup and the `smartchain.reload_tools` action; any two of
    those can land together. Gathering two is the shortest statement of that.
    """
    del patched_store
    entry = await _install(hass, tmp_path, second_entry=True, subentries=[_embeddings_subentry()])
    hass.config_entries.async_add_subentry(
        entry,
        registry_module.ConfigSubentry(
            data={
                "embeddings": EMBEDDINGS_TITLE,
                "description": "Dialogue history",
                "backend": {"type": "sqlite_numpy"},
                "retention_days": 90,
                "ingest_conversation": True,
            },
            subentry_type=SUBENTRY_TYPE_MEMORY_STORE,
            title="conversations",
            unique_id=None,
        ),
    )
    await hass.async_block_till_done()

    from custom_components.smartchain import _reload_registry

    watcher = _RebuildWatcher()
    with _watch(watcher, park=0.2):
        await asyncio.gather(_reload_registry(hass), _reload_registry(hass))
        await hass.async_block_till_done()

    _assert_memory_survived(hass, watcher)
    assert watcher.passes == 2
    assert watcher.entered_while_parked == 1, "the second rebuild ran inside the first"
    assert watcher.max_inside == 1


async def test_unloading_the_last_entry_waits_for_a_rebuild_in_flight(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    """Teardown takes the same lock as the rebuild.

    `async_unload_entry` stops the one MCP manager, shuts down the memory
    registry and stops the skeleton cache — the very three objects a rebuild is
    in the middle of replacing. Interleaved, the subsystems end up half torn
    down and half rebuilt.
    """
    del patched_store
    entry = await _install(hass, tmp_path, second_entry=False, subentries=[_embeddings_subentry()])
    from custom_components import smartchain

    order: list[str] = []
    real_rebuild = smartchain._rebuild_subsystems

    async def rebuild(h):
        order.append("rebuild-enter")
        await asyncio.sleep(0.2)
        try:
            return await real_rebuild(h)
        finally:
            order.append("rebuild-exit")

    # `SkeletonCache.stop` marks the teardown unambiguously: the unload path is
    # the only one that calls it. `MemoryRegistry.shutdown` and
    # `MCPManager.stop` would not do — a rebuild calls both itself.
    real_stop = entity_context.SkeletonCache.stop

    async def stop(self):
        order.append("teardown")
        return await real_stop(self)

    with (
        patch.object(smartchain, "_rebuild_subsystems", rebuild),
        patch.object(entity_context.SkeletonCache, "stop", stop),
    ):
        task = hass.async_create_task(smartchain._reload_registry(hass))
        await asyncio.sleep(0)  # let the rebuild take the lock
        await hass.config_entries.async_unload(entry.entry_id)
        await task

    assert order == ["rebuild-enter", "rebuild-exit", "teardown"], order


# --- the absent path ------------------------------------------------------


async def _create_tool_through_the_ha_dialog(hass: HomeAssistant, entry) -> None:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TOOL), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "kitchen_temperature",
            "description": "Read the kitchen temperature.",
            "enabled": True,
            "action_type": "template",
            "params_mode": "simple",
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"params_rows": [], "value_template": "{{ states('sensor.kitchen') }}"},
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()


def _tool_names(hass: HomeAssistant) -> list[str]:
    return [tool.name for tool in hass.data[DOMAIN]["tools"].all()]


@pytest.mark.parametrize("second_entry", [False, True])
async def test_a_tool_added_through_the_ha_dialog_reaches_the_registry(
    hass: HomeAssistant, tmp_path, second_entry
) -> None:
    """`ToolSubentryFlow` writes a subentry and calls no rebuild path of its own.

    Both cases are parametrised on purpose. With one entry this passed before
    the fix, and passed for the wrong reason: unloading the last entry sets
    `subsystems_stopped`, so the setup half of the reload rebuilt as a side
    effect. With a second entry configured that flag is never set, and the tool
    reached nothing at all — no error, no log line, just a tool that did not
    exist until `smartchain.reload_tools` or a restart.
    """
    entry = await _install(hass, tmp_path, second_entry=second_entry)
    await _create_tool_through_the_ha_dialog(hass, entry)
    assert "kitchen_temperature" in _tool_names(hass)


async def test_a_tool_edited_through_the_ha_dialog_reaches_the_registry(
    hass: HomeAssistant, tmp_path
) -> None:
    """Reconfigure goes through `async_update_and_abort`, a different write with
    the same gap."""
    entry = await _install(hass, tmp_path, second_entry=True)
    await _create_tool_through_the_ha_dialog(hass, entry)

    subentry = next(
        sub for sub in entry.subentries.values() if sub.subentry_type == SUBENTRY_TYPE_TOOL
    )
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TOOL),
        context={"source": "reconfigure", "subentry_id": subentry.subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "kitchen_humidity",
            "description": "Read the kitchen humidity.",
            "enabled": True,
            "action_type": "template",
            "params_mode": "simple",
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"params_rows": [], "value_template": "{{ states('sensor.humidity') }}"},
    )
    assert result["type"] == "abort"
    await hass.async_block_till_done()

    assert _tool_names(hass) == ["kitchen_humidity"]


async def test_a_store_added_through_the_ha_dialog_reaches_the_registry(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    """The memory-store dialog, the type whose absence of a rebuild was already
    on the follow-up list before two more types were added to it."""
    del patched_store
    entry = await _install(hass, tmp_path, second_entry=True, subentries=[_embeddings_subentry()])
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_MEMORY_STORE), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "conversations",
            "embeddings": EMBEDDINGS_TITLE,
            "backend_type": "sqlite_numpy",
            "source_type": "none",
        },
    )
    assert result["type"] == "form", result
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()

    assert hass.data[DOMAIN]["memory"].names() == ["conversations"]


async def test_an_options_save_that_touched_no_subentry_does_not_rebuild(
    hass: HomeAssistant, tmp_path
) -> None:
    """The rebuild is gated on a fingerprint for a reason: it bounces every MCP
    server and reopens every memory backend. An entry update that moved no
    subentry must not pay that."""
    entry = await _install(hass, tmp_path, second_entry=True)
    from custom_components import smartchain

    with patch.object(smartchain, "_rebuild_subsystems", AsyncMock(return_value=0)) as rebuild:
        hass.config_entries.async_update_entry(entry, options={"prompt": "hello"})
        await hass.async_block_till_done()

    rebuild.assert_not_awaited()
