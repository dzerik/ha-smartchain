"""SmartChain sensor platform — exposes Last Image Analysis as a proper entity."""

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
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

# `hass.data[DOMAIN]` key holding the entry_id of whichever config entry
# registered the singleton sensor. `async_unload_entry` clears it — and only
# for that entry_id. See `async_setup_entry` below for why it is an owner and
# not a bare boolean.
SENSOR_OWNER_KEY = "last_analysis_sensor_owner"


@callback
def async_release_sensor_owner(hass: HomeAssistant, entry_id: str) -> None:
    """Give up the singleton when its owning entry unloads.

    Called from `async_unload_entry`. The entry_id test is the whole point: with
    several hubs installed, unloading a *non-owner* must leave the owner's
    entity — which is still live — owning the slot, or the non-owner would try
    to add a second sensor on its way back in and Home Assistant would reject
    it as a duplicate unique_id.
    """
    domain_data = hass.data.get(DOMAIN)
    if domain_data is not None and domain_data.get(SENSOR_OWNER_KEY) == entry_id:
        domain_data.pop(SENSOR_OWNER_KEY, None)


async def async_rehome_sensor(hass: HomeAssistant, leaving_entry_id: str) -> None:
    """Re-register the released singleton on a hub that is still up.

    Releasing ownership is only half of an unload. The sensor is one entity for
    the whole of Home Assistant, but it lives on the *platform* of the entry
    that registered it, so unloading that entry takes the entity out of the
    state machine. On a reload the same entry brings it straight back; on a
    permanent unload — removing one hub of several, or disabling it — nothing
    does, and `sensor.smartchain_last_analysis` sits at `unavailable,
    restored=True` while another hub is still answering `analyze_image`. Every
    automation reading it goes quiet until some entry happens to reload.

    So the platform is re-forwarded to the first hub that is still loaded, which
    makes that entry the new owner. It stays one singleton: the platform is
    unloaded for the receiving entry first, because `EntityComponent` refuses a
    second setup of the same entry outright, and `async_setup_entry` below
    claims the slot before adding anything.

    Called after `async_release_sensor_owner`, and does nothing unless that call
    actually freed the slot — a non-owner unloading must not move an entity
    that is perfectly alive where it is.
    """
    domain_data = hass.data.get(DOMAIN)
    if domain_data is None or domain_data.get(SENSOR_OWNER_KEY) is not None:
        return

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == leaving_entry_id or entry.state is not ConfigEntryState.LOADED:
            continue
        try:
            await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])
            await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
        except Exception:
            # Never let this fail an unload: the entry being unloaded is not the
            # one that misbehaved, and its teardown must still report honestly.
            # Hand the slot back so the next reload of any hub can retry —
            # otherwise a claim taken just before the failure would lock every
            # other entry out of registering the sensor for the rest of the run.
            LOGGER.exception(
                "Could not move the SmartChain Last Analysis sensor to %s", entry.entry_id
            )
            async_release_sensor_owner(hass, entry.entry_id)
        return


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Last Analysis sensor once per HA instance.

    The sensor is a domain-wide singleton (one Last Analysis across all config
    entries) — the first entry to be set up registers it and becomes its owner;
    subsequent entries skip the add.

    What is recorded is the owner's entry_id, not a "registered" boolean. The
    boolean only ever considered a full HA reboot, and the sensor lives on the
    owning entry's *platform*: unloading that entry takes the entity down while
    the flag stayed set, so the `async_setup_entry` half of a reload returned
    early and the sensor stayed `unavailable` until Home Assistant restarted.
    Every options and agent edit in the UI ends in `async_reload`, so this was
    a routine edit silently killing `sensor.smartchain_last_analysis` and every
    automation reading it.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(SENSOR_OWNER_KEY) is not None:
        return
    domain_data[SENSOR_OWNER_KEY] = entry.entry_id
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
