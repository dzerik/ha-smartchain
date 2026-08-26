"""What one subentry write costs on a single-entry install — the common shape.

`tests/test_subentry_rebuild.py` proves a subentry write *reaches* the shared
subsystems. It says nothing about the price, and the one case it does
parametrise over the install shape it parametrises for reachability only. The
fingerprint gate added in 5.4.4 was therefore never measured on an install with
a single config entry, which is the shape most users have — and on that shape
it is bypassed entirely: `async_reload` unloads the last entry, the unload sets
`subsystems_stopped`, and the next `async_setup_entry` rebuilds unconditionally,
after the websocket handler already rebuilt.

Worse than the duplicate rebuild is the reload itself. A tool subentry has
nothing to do with the client an agent is built from, but switching one on
reloaded the whole hub: every `conversation.*` entity was removed and re-added,
so an Assist request landing in that window failed. Installing three ready-made
tools cost three full setup cycles, six entity transitions and six embedding
round-trips — each of the latter a fresh OAuth exchange against the provider
under a 30 s timeout.

This file measures. Every test here asserts a number.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import smartchain
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_ANTHROPIC,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
    SUBENTRY_TYPE_MEMORY_STORE,
    SUBENTRY_TYPE_TOOL,
    UNIQUE_ID_ANTHROPIC,
    UNIQUE_ID_OPENAI,
)
from custom_components.smartchain.tools.memory import registry as registry_module

pytestmark = pytest.mark.usefixtures("enable_custom_integrations", "mock_get_client")

EMBEDDINGS_TITLE = "OpenAI Embeddings"


class _Meter:
    """Everything one subentry write is allowed to cost, counted.

    `setups` and `unloads` are the hub going down and coming back.
    `offline` counts a `conversation.*` entity leaving the state machine or
    going unavailable — what an Assist request in that window actually hits.
    `probes` counts `embed_query` against the embeddings provider: a real
    round-trip, a fresh OAuth exchange, a 30 s timeout.
    """

    def __init__(self) -> None:
        self.setups = 0
        self.unloads = 0
        self.rebuilds = 0
        self.offline: list[str] = []
        self.probes = 0

    def __str__(self) -> str:  # pragma: no cover - only in failure messages
        return (
            f"setups={self.setups} unloads={self.unloads} rebuilds={self.rebuilds} "
            f"offline={self.offline} probes={self.probes}"
        )


@pytest.fixture
def meter(hass: HomeAssistant):
    """Instrument the four costs, and hand back the counter."""
    m = _Meter()

    real_setup = smartchain.async_setup_entry
    real_unload = smartchain.async_unload_entry
    real_rebuild = smartchain._rebuild_subsystems

    async def setup_entry(h, entry):
        m.setups += 1
        return await real_setup(h, entry)

    async def unload_entry(h, entry):
        m.unloads += 1
        return await real_unload(h, entry)

    async def rebuild(h):
        m.rebuilds += 1
        return await real_rebuild(h)

    def watch(event) -> None:
        if not event.data["entity_id"].startswith("conversation."):
            return
        new = event.data.get("new_state")
        if new is None or new.state == STATE_UNAVAILABLE:
            m.offline.append(event.data["entity_id"])

    def embeddings_factory(hass_, entry, subentry):
        provider = MagicMock()

        async def embed_query(_text):
            m.probes += 1
            return [0.0, 1.0, 0.0]

        async def embed_documents(texts):
            return [[0.0, 1.0, 0.0] for _ in texts]

        provider.embed_query = embed_query
        provider.embed_documents = embed_documents
        provider.model = "text-embedding-3-small"
        return provider

    hass.bus.async_listen(EVENT_STATE_CHANGED, watch)

    with (
        patch.object(smartchain, "async_setup_entry", setup_entry),
        patch.object(smartchain, "async_unload_entry", unload_entry),
        patch.object(smartchain, "_rebuild_subsystems", rebuild),
        patch.object(
            registry_module, "create_embeddings_from_subentry", side_effect=embeddings_factory
        ),
    ):
        yield m


@pytest.fixture
def patched_backend():
    """A backend that starts, so `async_setup` reaches the embedding probe.

    Deliberately *not* the `patched_store` stand-in of
    `tests/test_subentry_rebuild.py`: that one replaces `MemoryStore` whole, so
    `async_setup` becomes an `AsyncMock` and the embedding round-trip this file
    is counting never happens.
    """
    from custom_components.smartchain.tools.memory import backends

    def _factory(hass_, config, store_name, storage_dir):
        backend = MagicMock()
        backend.name = "sqlite_numpy"
        backend.initialize = AsyncMock()
        backend.close = AsyncMock()
        backend.add = AsyncMock()
        backend.query = AsyncMock(return_value=[])
        backend.list_metadata = AsyncMock(return_value=[])
        backend.delete_where = AsyncMock(return_value=0)
        backend.update_metadata = AsyncMock()
        backend.delete_older_than = AsyncMock(return_value=0)
        backend.count = AsyncMock(return_value=0)
        return backend

    with patch.object(registry_module, "create_backend", side_effect=_factory):
        yield backends


def _agent(name: str) -> ConfigSubentryData:
    return ConfigSubentryData(
        data={"model": "gpt-4o-mini", "prompt": "hi"},
        subentry_type=SUBENTRY_TYPE_CONVERSATION,
        title=name,
        unique_id=None,
    )


def _embeddings() -> ConfigSubentryData:
    return ConfigSubentryData(
        data={"model": "text-embedding-3-small"},
        subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
        title=EMBEDDINGS_TITLE,
        unique_id=None,
    )


def _store() -> ConfigSubentryData:
    return ConfigSubentryData(
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
    )


async def _install(hass: HomeAssistant, tmp_path, *, second_entry: bool = False):
    """The user's shape: one hub, two agents, an embeddings binding, a store."""
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        options={},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        minor_version=4,
        subentries_data=[_agent("Main"), _agent("Second"), _embeddings(), _store()],
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


def _tool_names(hass: HomeAssistant) -> list[str]:
    return [tool.name for tool in hass.data[DOMAIN]["tools"].all()]


async def _create_tool_through_the_ha_dialog(hass, entry, name: str) -> None:
    """Home Assistant's own subentry dialog — the writer with no websocket handler."""
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TOOL), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": name,
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
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()


async def _install_preset(hass, client, entry, preset: str) -> None:
    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/preset/install",
            "entry_id": entry.entry_id,
            "preset": preset,
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["ok"], msg["result"]
    assert msg["result"]["reload_error"] is None, msg["result"]
    await hass.async_block_till_done()


# --- the measurement ------------------------------------------------------


async def test_installing_three_presets_costs_three_rebuilds_and_no_reload(
    hass: HomeAssistant, hass_ws_client, tmp_path, meter, patched_backend
) -> None:
    """The headline number, on the install shape that has one config entry.

    Measured before the fix: 3 setup cycles, 3 unloads, 6 rebuilds, 6
    `conversation.*` transitions and 6 embedding round-trips — two agents
    dropping and returning on every tool the user switched on.

    A tool subentry is not part of any agent's client. Switching one on must
    cost exactly one rebuild of the shared subsystems and must not touch the
    config entry at all.
    """
    del patched_backend
    entry = await _install(hass, tmp_path)
    assert len(hass.data[DOMAIN]["memory"].names()) == 1, "the store did not start"
    client = await hass_ws_client(hass)

    meter.setups = meter.unloads = meter.rebuilds = meter.probes = 0
    meter.offline.clear()

    for preset in ("weather_forecast", "sun_times", "who_is_home"):
        await _install_preset(hass, client, entry, preset)

    assert meter.setups == 0, f"the hub was rebuilt by a tool write: {meter}"
    assert meter.unloads == 0, f"the hub was torn down by a tool write: {meter}"
    assert meter.offline == [], f"agents went offline for a tool write: {meter}"
    assert meter.rebuilds == 3, f"one rebuild per write, not {meter.rebuilds}: {meter}"
    assert meter.probes == 3, f"one probe per rebuild, not {meter.probes}: {meter}"

    for preset in ("weather_forecast", "sun_times", "who_is_home"):
        assert preset in _tool_names(hass)


async def test_one_tool_write_is_one_rebuild_on_a_single_entry_install(
    hass: HomeAssistant, hass_ws_client, tmp_path, meter, patched_backend
) -> None:
    """The 5.4.4 fingerprint gate, finally measured on one entry.

    The gate returns early when the fingerprint the last rebuild recorded still
    matches — which it does, because the websocket handler rebuilt and recorded
    it before this listener ran. On a single-entry install that early return was
    unreachable in the way that mattered: the `async_reload` *above* it had
    already unloaded the last entry, set `subsystems_stopped`, and let
    `async_setup_entry` rebuild unconditionally. The gate prevented a third
    rebuild, never the second.
    """
    del patched_backend
    entry = await _install(hass, tmp_path)
    client = await hass_ws_client(hass)

    meter.rebuilds = meter.setups = 0
    await _install_preset(hass, client, entry, "sun_times")

    assert meter.rebuilds == 1, f"{meter.rebuilds} rebuilds for one write: {meter}"
    assert meter.setups == 0, f"{meter.setups} setup cycles for one write: {meter}"


async def test_a_tool_written_through_the_ha_dialog_costs_one_rebuild_and_no_reload(
    hass: HomeAssistant, tmp_path, meter, patched_backend
) -> None:
    """The other writer of the same subentry: Home Assistant's own dialog.

    There is no websocket handler here and nothing has rebuilt when
    `update_listener` runs, so this is the path where the listener's rebuild is
    the *only* one. It must still be one, and it must still not reload the hub.
    """
    del patched_backend
    entry = await _install(hass, tmp_path)

    meter.rebuilds = meter.setups = meter.unloads = 0
    meter.offline.clear()

    await _create_tool_through_the_ha_dialog(hass, entry, "kitchen_temperature")

    assert "kitchen_temperature" in _tool_names(hass)
    assert meter.rebuilds == 1, f"{meter.rebuilds} rebuilds: {meter}"
    assert meter.setups == 0, f"the dialog reloaded the hub: {meter}"
    assert meter.offline == [], f"agents went offline for a tool write: {meter}"


@pytest.mark.parametrize("second_entry", [False, True])
async def test_a_tool_write_costs_the_same_on_either_install_shape(
    hass: HomeAssistant, hass_ws_client, tmp_path, meter, patched_backend, second_entry
) -> None:
    """The whole reason this survived: the existing coverage used two entries.

    With two entries `async_reload` never unloads the last one, so
    `subsystems_stopped` is never set and the duplicate rebuild never happened —
    the two-entry case passed throughout. Pinning both shapes to the same number
    is what stops the single-entry case regressing again.
    """
    del patched_backend
    entry = await _install(hass, tmp_path, second_entry=second_entry)
    client = await hass_ws_client(hass)

    meter.rebuilds = meter.setups = 0
    meter.offline.clear()
    await _install_preset(hass, client, entry, "sun_times")

    assert meter.rebuilds == 1, f"{meter.rebuilds} rebuilds: {meter}"
    assert meter.setups == 0, f"{meter.setups} setup cycles: {meter}"
    assert meter.offline == [], f"agents went offline: {meter}"


# --- what must still reload ----------------------------------------------


async def test_saving_an_agent_still_reloads_the_hub(
    hass: HomeAssistant, hass_ws_client, tmp_path, meter, patched_backend
) -> None:
    """The reload is not gone, only spent where it is needed.

    An agent's model, prompt and options are what `async_setup_entry` builds
    its client and its `conversation.*` entity from. `ws_agent_save` calls no
    rebuild path of its own and never has: the entry reload the update listener
    performs *is* how an edited agent takes effect.
    """
    del patched_backend
    entry = await _install(hass, tmp_path)
    subentry = next(
        sub
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_TYPE_CONVERSATION and sub.title == "Main"
    )
    client = await hass_ws_client(hass)

    meter.setups = meter.rebuilds = 0
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "subentry_id": subentry.subentry_id,
            "data": {"model": "gpt-4o", "prompt": "changed"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    await hass.async_block_till_done()

    assert meter.setups == 1, f"an agent edit did not reload the hub: {meter}"
    assert entry.subentries[subentry.subentry_id].data["prompt"] == "changed"


async def test_a_connection_settings_save_still_reloads_the_hub(
    hass: HomeAssistant, tmp_path, meter, patched_backend
) -> None:
    """An options write moves no subentry, so the fingerprint is unchanged — but
    the entry's own data is what every client is built from, and that has to be
    picked up. One reload, and no rebuild of the shared subsystems on top."""
    del patched_backend
    entry = await _install(hass, tmp_path)

    meter.setups = meter.rebuilds = 0
    hass.config_entries.async_update_entry(entry, options={"prompt": "hello"})
    await hass.async_block_till_done()

    assert meter.setups == 1, f"the options save did not reload: {meter}"
    # One rebuild, not two: the reload of the only entry tears the subsystems
    # down, so the setup half has to bring them back. The listener must not
    # then rebuild a second time on top of it.
    assert meter.rebuilds == 1, f"{meter.rebuilds} rebuilds for an options save: {meter}"


@pytest.mark.parametrize("second_entry", [False, True])
async def test_an_options_save_and_a_tool_write_cost_one_each(
    hass: HomeAssistant, tmp_path, meter, patched_backend, second_entry
) -> None:
    """Both kinds of change, back to back, each paying only for itself.

    The options save is the expensive one and must reload. The tool write must
    not. On a single-entry install the options save's reload also tears the
    subsystems down, so its setup half rebuilds them — and the gated call the
    listener makes afterwards must then find nothing to do, or the pair costs
    three rebuilds for two writes.

    Parametrised over the install shape because the two shapes reach the same
    total by different routes: with one entry the first rebuild comes from
    `subsystems_stopped` inside setup, with two it comes from the listener's
    own gated call.
    """
    del patched_backend
    entry = await _install(hass, tmp_path, second_entry=second_entry)

    meter.setups = meter.rebuilds = 0
    hass.config_entries.async_update_entry(entry, options={"prompt": "hello"})
    await hass.async_block_till_done()

    assert meter.setups == 1, f"the options save: {meter}"
    # With a second entry nothing is torn down and no subsystem subentry moved,
    # so the options save rebuilds nothing at all.
    expected_after_options = 1 if not second_entry else 0
    assert meter.rebuilds == expected_after_options, f"the options save: {meter}"

    await _create_tool_through_the_ha_dialog(hass, entry, "kitchen_temperature")

    assert meter.setups == 1, f"the tool write reloaded the hub: {meter}"
    assert meter.rebuilds == expected_after_options + 1, f"the tool write: {meter}"
    assert "kitchen_temperature" in _tool_names(hass)


async def test_a_removed_entry_leaves_no_fingerprint_behind(
    hass: HomeAssistant, tmp_path, patched_backend
) -> None:
    """The digest is about a live setup and does not outlive one.

    It is keyed by `entry_id`, so without the cleanup a user who adds and
    removes hubs accumulates one dead digest per removal for the rest of the
    process. Small, but unbounded and never read again.

    What this is *not* protecting against: a stale digest suppressing a reload
    an unloaded entry needed. It cannot — the listener is registered through
    `entry.async_on_unload`, so unloading takes the listener with it and no
    write on an unloaded entry reaches this code at all. A second entry is
    configured here so the removal is an ordinary one rather than the
    last-entry teardown.
    """
    del patched_backend
    entry = await _install(hass, tmp_path, second_entry=True)
    fingerprints = hass.data[DOMAIN]["entry_fingerprints"]
    assert entry.entry_id in fingerprints

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.entry_id not in fingerprints, "the removed entry's digest outlived it"


SIMPLE_TOOL = {
    "name": "porch_light",
    "description": "Turn the porch light on.",
    "enabled": True,
    "action_type": "service",
    "params_mode": "simple",
    "params_rows": [],
    "service": "light.turn_on",
    "target": {"entity_id": ["light.porch"]},
    "service_data": {},
    "response": False,
}


async def test_a_save_the_gate_skips_still_reports_a_broken_tools_yaml(
    hass: HomeAssistant, hass_ws_client, tmp_path, meter, patched_backend
) -> None:
    """Skipping the rebuild must not read as "the file is fine now".

    `reload_error` is what puts the standing banner on the Tools tab. It used
    to be `None` only when a rebuild had just run cleanly; now the rebuild can
    be skipped, and a skip that answered `None` would clear the banner on a
    file that is exactly as broken as it was a moment ago.

    Both saves below exercise the skip, by two different routes, and neither is
    contrived. The **first** hits it because the update listener the same write
    scheduled usually wins the race, rebuilds, hits the broken file and records
    the fingerprint before the handler gets there — so the handler that has to
    answer the user is precisely the one that did not read the file. The
    **second** re-saves the same subentry with the same values, so nothing moves
    at all and no rebuild happens by either route. Which of the two the first
    save takes is a scheduling detail, so it is not asserted; that it answers
    with the error is.
    """
    del patched_backend
    entry = await _install(hass, tmp_path)
    (tmp_path / "smartchain").mkdir(parents=True, exist_ok=True)
    (tmp_path / "smartchain" / "tools.yaml").write_text(
        "tools:\n  - name: x\n   description: bad indent\n"
    )
    client = await hass_ws_client(hass)

    async def save(subentry_id: str | None = None) -> tuple[str, str | None]:
        payload = {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "data": SIMPLE_TOOL,
        }
        if subentry_id is not None:
            payload["subentry_id"] = subentry_id
        await client.send_json_auto_id(payload)
        msg = await client.receive_json()
        assert msg["success"], msg
        await hass.async_block_till_done()
        return msg["result"]["subentry_id"], msg["result"]["reload_error"]

    # A real write, which one of the two paths rebuilds for. Whichever it was,
    # the answer the user gets names the broken file.
    subentry_id, first = await save()
    assert first, "the broken file was not reported to the save that landed on it"

    # The identical write, re-saving the same subentry: nothing moved, so
    # nothing rebuilds — and the same error still comes back.
    meter.rebuilds = 0
    _same_id, second = await save(subentry_id)
    assert meter.rebuilds == 0, f"a no-op save rebuilt: {meter}"
    assert second == first, f"the standing error changed on a skipped rebuild: {second!r}"
