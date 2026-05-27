"""Tests for the smartchain.reload_tools service."""

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.smartchain import async_setup
from custom_components.smartchain.const import (
    DOMAIN,
    EVENT_TOOLS_RELOADED,
    SERVICE_RELOAD_TOOLS,
)


@pytest.fixture
def tools_dir(hass: HomeAssistant, tmp_path_factory) -> Path:
    """Point hass.config.config_dir at a writable temp dir with a smartchain/ subdir."""
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    hass.config.config_dir = str(cdir)
    return cdir / "smartchain"


async def test_reload_loads_yaml_and_fires_event(hass: HomeAssistant, tools_dir: Path) -> None:
    """reload_tools reads tools.yaml and fires the reloaded event."""
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: pong }\n"
    )
    await async_setup(hass, {})

    events = []
    hass.bus.async_listen(EVENT_TOOLS_RELOADED, lambda e: events.append(e))

    await hass.services.async_call(DOMAIN, SERVICE_RELOAD_TOOLS, {}, blocking=True)
    await hass.async_block_till_done()

    assert hass.data[DOMAIN]["tools"].get("ping") is not None
    assert len(events) == 1
    assert events[0].data["count"] == 1


async def test_reload_invalid_yaml_raises_and_keeps_old(
    hass: HomeAssistant, tools_dir: Path
) -> None:
    """Failed reload raises HomeAssistantError and does NOT clobber the existing registry."""
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: pong }\n"
    )
    await async_setup(hass, {})
    assert hass.data[DOMAIN]["tools"].get("ping") is not None

    (tools_dir / "tools.yaml").write_text("tools: [{ name: Bad-Name, description: x }]")

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, SERVICE_RELOAD_TOOLS, {}, blocking=True)

    # Old registry intact
    assert hass.data[DOMAIN]["tools"].get("ping") is not None
