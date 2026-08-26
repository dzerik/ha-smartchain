"""Lifecycle tests for the Last Analysis sensor singleton.

The sensor is a domain-wide singleton registered by whichever config entry is
set up first. These tests pin the *entity* — what `hass.states` holds — across
reload and unload, because the bookkeeping in `hass.data` that decides whether
to register it is exactly the implementation detail under change.
"""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components import smartchain
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
    SIGNAL_NEW_ANALYSIS,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SENSOR_ENTITY_ID = "sensor.smartchain_last_analysis"


async def _setup_entry(hass: HomeAssistant, mock_client, unique_id: str) -> MockConfigEntry:
    """Set up a real config entry so every platform (incl. sensor) is loaded."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test-credentials"},
        options={},
        unique_id=unique_id,
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _assert_sensor_alive(hass: HomeAssistant, context: str) -> None:
    """The sensor exists and is a live entity, not a restored husk."""
    state = hass.states.get(SENSOR_ENTITY_ID)
    assert state is not None, f"sensor gone {context}"
    assert state.state != "unavailable", f"sensor unavailable {context}"
    assert not state.attributes.get("restored"), f"sensor only restored {context}"


async def test_sensor_survives_entry_reload(hass: HomeAssistant, mock_llm_client) -> None:
    """Reloading the entry that registered the sensor must bring it back.

    Every options/agent edit in the UI ends in `async_reload`, so a sensor that
    dies here is dead until Home Assistant itself restarts.
    """
    entry = await _setup_entry(hass, mock_llm_client, "GigaChat")
    _assert_sensor_alive(hass, "before reload")

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after reload")


async def test_sensor_survives_owner_reload_with_second_entry(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """A second hub must not stop the owner from re-registering on reload."""
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_reload(first.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after reloading the owner")


async def test_unloading_other_entry_leaves_sensor_owned(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Unloading a non-owner entry touches neither the sensor nor its ownership.

    Ownership has to be released per entry_id, not unconditionally: releasing it
    here would let the second entry try to add a *second* singleton on its way
    back in, which Home Assistant rejects as a duplicate unique_id.
    """
    await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")

    await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()
    _assert_sensor_alive(hass, "after unloading the second entry")

    caplog.clear()
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(second.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after the second entry came back")
    assert "does not generate unique IDs" not in caplog.text


async def test_sensor_moves_to_a_surviving_hub_when_its_owner_unloads(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """A permanent unload of the owner must not take the singleton down with it.

    The sensor lives on the *platform* of whichever entry registered it, so
    unloading that entry removes the entity. That is right when it was the last
    hub and wrong while another one is still serving `analyze_image`: the
    automations reading `sensor.smartchain_last_analysis` go quiet until some
    entry happens to reload.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")

    caplog.clear()
    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after the owner was unloaded for good")
    # Still one sensor for the whole of Home Assistant, now carried by the hub
    # that is still up — not a second entity added beside the first.
    ent_reg = er.async_get(hass)
    owned = [
        ent
        for ent in ent_reg.entities.values()
        if ent.platform == DOMAIN and ent.domain == "sensor"
    ]
    assert len(owned) == 1
    assert owned[0].config_entry_id == second.entry_id
    assert "does not generate unique IDs" not in caplog.text


async def test_sensor_keeps_its_reading_across_the_move(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """The move must carry the last analysis over, not blank it."""
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    await _setup_entry(hass, mock_llm_client, "GigaChat-2")

    async_dispatcher_send(
        hass,
        SIGNAL_NEW_ANALYSIS,
        {
            "response": "a cat on the porch",
            "camera_entity_id": "camera.porch",
            "message": "what do you see?",
            "timestamp": "2026-08-26T12:00:00+00:00",
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ENTITY_ID).state == "a cat on the porch"

    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(SENSOR_ENTITY_ID)
    assert state.state == "a cat on the porch"
    assert state.attributes["camera_entity_id"] == "camera.porch"


async def test_sensor_is_released_when_only_another_platform_fails_to_unload(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """One stuck platform must not cost the singleton its slot.

    `async_unload_platforms` answers for all platforms at once: a conversation
    platform that refuses to unload makes it False even though the sensor
    platform went down cleanly and took the entity with it. Gating the release
    of ownership on that combined answer leaves the slot held by an entry that
    no longer has the entity — and every other hub then skips registering it.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")

    real_unload = hass.config_entries.async_forward_entry_unload

    async def _refuse_conversation(entry, domain):
        if entry.entry_id == first.entry_id and domain == Platform.CONVERSATION:
            return False
        return await real_unload(entry, domain)

    with patch.object(
        hass.config_entries, "async_forward_entry_unload", side_effect=_refuse_conversation
    ):
        assert not await hass.config_entries.async_unload(first.entry_id)
        await hass.async_block_till_done()

    # The surviving hub reloads — as every options edit makes it do — and must
    # be able to claim a slot the half-unloaded entry has no entity for.
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_reload(second.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after the surviving hub reloaded")


def test_sensor_platform_is_not_imported_at_module_scope() -> None:
    """`__init__.py` keeps platform and websocket modules off its import path.

    The file states the convention on its `websocket_api` imports: those are
    deferred into the functions that need them. `.sensor` is a platform module,
    loaded by Home Assistant when the platform is forwarded, and it has no
    business being pulled in when the integration package is merely imported.
    """
    tree = ast.parse(Path(smartchain.__file__).read_text(encoding="utf-8"))
    module_level = [
        node.module for node in tree.body if isinstance(node, ast.ImportFrom) and node.level == 1
    ]
    assert "sensor" not in module_level
    assert "websocket_api" not in module_level
