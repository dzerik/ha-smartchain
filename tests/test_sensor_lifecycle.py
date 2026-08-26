"""Lifecycle tests for the Last Analysis sensor singleton.

The sensor is a domain-wide singleton registered by whichever config entry is
set up first. These tests pin the *entity* — what `hass.states` holds — across
reload and unload, because the bookkeeping in `hass.data` that decides whether
to register it is exactly the implementation detail under change.
"""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
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
