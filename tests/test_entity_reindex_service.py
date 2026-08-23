"""Forcing a sweep, and failing loudly when asked to sweep nothing."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.smartchain import async_setup
from custom_components.smartchain.const import (
    DOMAIN,
    EVENT_ENTITIES_REINDEXED,
    SERVICE_REINDEX_ENTITIES,
)
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer, SweepResult
from custom_components.smartchain.tools.memory.registry import MemoryRegistry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
def tools_dir(hass: HomeAssistant, tmp_path_factory):
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    hass.config.config_dir = str(cdir)
    return cdir / "smartchain"


def _registry(hass: HomeAssistant, names: list[str]) -> dict[str, MagicMock]:
    indexers = {}
    for name in names:
        indexer = MagicMock(spec=EntityIndexer)
        indexer.reconcile = AsyncMock(
            return_value=SweepResult(new=1, changed=2, removed=3, unchanged=4)
        )
        indexers[name] = indexer

    reg = MagicMock(spec=MemoryRegistry)
    reg.entity_store_names.return_value = names
    reg.indexer_for.side_effect = indexers.get
    hass.data.setdefault(DOMAIN, {})["memory"] = reg
    return indexers


async def test_reindex_sweeps_every_store_by_default(hass: HomeAssistant, tools_dir) -> None:
    (tools_dir / "tools.yaml").write_text("tools: []\n")
    await async_setup(hass, {})
    indexers = _registry(hass, ["entities", "rooms"])

    events: list = []
    hass.bus.async_listen(EVENT_ENTITIES_REINDEXED, lambda e: events.append(e))

    await hass.services.async_call(DOMAIN, SERVICE_REINDEX_ENTITIES, {}, blocking=True)
    await hass.async_block_till_done()

    assert all(i.reconcile.await_count == 1 for i in indexers.values())
    assert sorted(events[0].data["stores"]) == ["entities", "rooms"]
    assert events[0].data["new"] == 2
    assert events[0].data["unchanged"] == 8


async def test_reindex_targets_one_store(hass: HomeAssistant, tools_dir) -> None:
    (tools_dir / "tools.yaml").write_text("tools: []\n")
    await async_setup(hass, {})
    indexers = _registry(hass, ["entities", "rooms"])

    await hass.services.async_call(
        DOMAIN, SERVICE_REINDEX_ENTITIES, {"store": "entities"}, blocking=True
    )
    await hass.async_block_till_done()

    assert indexers["entities"].reconcile.await_count == 1
    assert indexers["rooms"].reconcile.await_count == 0


async def test_full_is_passed_through(hass: HomeAssistant, tools_dir) -> None:
    (tools_dir / "tools.yaml").write_text("tools: []\n")
    await async_setup(hass, {})
    indexers = _registry(hass, ["entities"])

    await hass.services.async_call(DOMAIN, SERVICE_REINDEX_ENTITIES, {"full": True}, blocking=True)
    await hass.async_block_till_done()

    assert indexers["entities"].reconcile.await_args.kwargs["full"] is True


async def test_unknown_store_raises_and_names_the_real_ones(hass: HomeAssistant, tools_dir) -> None:
    (tools_dir / "tools.yaml").write_text("tools: []\n")
    await async_setup(hass, {})
    _registry(hass, ["entities"])

    with pytest.raises(HomeAssistantError, match="entities"):
        await hass.services.async_call(
            DOMAIN, SERVICE_REINDEX_ENTITIES, {"store": "ghost"}, blocking=True
        )


async def test_no_entity_store_raises(hass: HomeAssistant, tools_dir) -> None:
    (tools_dir / "tools.yaml").write_text("tools: []\n")
    await async_setup(hass, {})
    _registry(hass, [])

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, SERVICE_REINDEX_ENTITIES, {}, blocking=True)
