"""SmartChain sensor platform — exposes Last Image Analysis as a proper entity."""

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, SIGNAL_NEW_ANALYSIS

LOGGER = logging.getLogger(__name__)

# Cap full_response so a runaway LLM response doesn't pollute the recorder DB or
# WS payloads. HA's state value is already truncated to 255 chars; this caps the
# extra attribute that downstream automations may need in full.
_MAX_FULL_RESPONSE_LEN = 4096


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Last Analysis sensor once per HA instance.

    The sensor is a domain-wide singleton (one Last Analysis across all config
    entries) — the first entry to be set up registers it; subsequent entries
    skip the add. The flag lives in hass.data so a full HA reboot re-runs the
    registration.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("last_analysis_sensor_added"):
        return
    domain_data["last_analysis_sensor_added"] = True
    async_add_entities([SmartChainLastAnalysisSensor()])


class SmartChainLastAnalysisSensor(SensorEntity, RestoreEntity):
    """Reflects the most recent smartchain.analyze_image result."""

    _attr_name = "SmartChain Last Analysis"
    _attr_icon = "mdi:camera-iris"
    _attr_unique_id = f"{DOMAIN}_last_analysis"
    _attr_should_poll = False

    def __init__(self) -> None:
        """Initialise with empty state."""
        self._attr_native_value: str | None = None
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Restore last state and subscribe to analysis events."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state not in (None, "unknown", "unavailable"):
            self._attr_native_value = last.state
            self._attr_extra_state_attributes = {
                k: v for k, v in last.attributes.items() if k not in ("icon", "friendly_name")
            }
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_NEW_ANALYSIS, self._handle_new)
        )

    @callback
    def _handle_new(self, data: dict[str, Any]) -> None:
        """Update sensor from an analyze_image dispatch payload."""
        text = data.get("response") or ""
        self._attr_native_value = text[:255]
        self._attr_extra_state_attributes = {
            "camera_entity_id": data.get("camera_entity_id"),
            "message": data.get("message"),
            "full_response": text[:_MAX_FULL_RESPONSE_LEN],
            "timestamp": data.get("timestamp"),
        }
        self.async_write_ha_state()
