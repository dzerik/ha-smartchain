"""Tests for SmartChain Last Analysis sensor."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
    SIGNAL_NEW_ANALYSIS,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SENSOR_ENTITY_ID = "sensor.smartchain_last_analysis"


async def _setup_full_entry(hass: HomeAssistant, mock_client) -> MockConfigEntry:
    """Set up a real config entry so all platforms (incl. sensor) are loaded."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test-credentials"},
        options={},
        unique_id="GigaChat",
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


async def test_sensor_is_created(hass: HomeAssistant, mock_llm_client) -> None:
    """The Last Analysis sensor is created when an entry is set up."""
    await _setup_full_entry(hass, mock_llm_client)
    state = hass.states.get(SENSOR_ENTITY_ID)
    assert state is not None


async def test_sensor_updates_from_dispatch(hass: HomeAssistant, mock_llm_client) -> None:
    """Sensor reflects payloads dispatched on SIGNAL_NEW_ANALYSIS."""
    await _setup_full_entry(hass, mock_llm_client)

    async_dispatcher_send(
        hass,
        SIGNAL_NEW_ANALYSIS,
        {
            "response": "Garage door is open",
            "camera_entity_id": "camera.garage",
            "message": "Check garage",
            "timestamp": "2026-05-27T12:00:00+00:00",
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get(SENSOR_ENTITY_ID)
    assert state is not None
    assert state.state == "Garage door is open"
    assert state.attributes["camera_entity_id"] == "camera.garage"
    assert state.attributes["message"] == "Check garage"
    assert state.attributes["full_response"] == "Garage door is open"
    assert state.attributes["timestamp"] == "2026-05-27T12:00:00+00:00"


async def test_sensor_caps_full_response(hass: HomeAssistant, mock_llm_client) -> None:
    """`full_response` is capped to keep recorder/WS payloads bounded."""
    await _setup_full_entry(hass, mock_llm_client)

    huge = "x" * 10_000
    async_dispatcher_send(
        hass,
        SIGNAL_NEW_ANALYSIS,
        {
            "response": huge,
            "camera_entity_id": "camera.test",
            "message": "test",
            "timestamp": "2026-05-27T12:00:00+00:00",
        },
    )
    await hass.async_block_till_done()

    state = hass.states.get(SENSOR_ENTITY_ID)
    assert state is not None
    assert len(state.state) == 255
    assert len(state.attributes["full_response"]) == 4096


async def test_sensor_singleton_across_entries(hass: HomeAssistant, mock_llm_client) -> None:
    """A second config entry must not create a second Last Analysis sensor."""
    await _setup_full_entry(hass, mock_llm_client)

    second = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "second"},
        options={},
        unique_id="GigaChat-2",
    )
    second.add_to_hass(hass)
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(second.entry_id)
        await hass.async_block_till_done()

    sensors = [s for s in hass.states.async_all() if s.entity_id == SENSOR_ENTITY_ID]
    assert len(sensors) == 1
