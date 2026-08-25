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


async def test_reload_count_excludes_disabled_tools(hass: HomeAssistant, tools_dir: Path) -> None:
    """The reloaded event's `count` reflects only what actually loaded — a
    disabled tool must not be counted, must not be dispatchable, and must not
    appear in the registry's names()."""
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: pong }\n"
        "  - name: off_tool\n"
        "    description: turned off while debugging\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: pong }\n"
        "    enabled: false\n"
    )
    await async_setup(hass, {})

    events = []
    hass.bus.async_listen(EVENT_TOOLS_RELOADED, lambda e: events.append(e))

    await hass.services.async_call(DOMAIN, SERVICE_RELOAD_TOOLS, {}, blocking=True)
    await hass.async_block_till_done()

    registry = hass.data[DOMAIN]["tools"]
    assert events[0].data["count"] == 1
    assert registry.get("ping") is not None
    assert registry.get("off_tool") is None
    assert "off_tool" not in registry.names()


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


async def test_reload_resolves_secret_from_the_ha_config_dir(
    hass: HomeAssistant, tools_dir: Path
) -> None:
    """`!secret` in tools.yaml resolves against <config>/secrets.yaml.

    Before the config dir was threaded into the loader, HA failed the whole
    file with "Secrets not supported in this YAML file".
    """
    (tools_dir.parent / "secrets.yaml").write_text("ping_reply: pong-from-secrets\n")
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: !secret ping_reply }\n"
    )
    await async_setup(hass, {})

    await hass.services.async_call(DOMAIN, SERVICE_RELOAD_TOOLS, {}, blocking=True)
    await hass.async_block_till_done()

    tool = hass.data[DOMAIN]["tools"].get("ping")
    assert tool is not None
    assert tool.action.value_template == "pong-from-secrets"


def test_services_yaml_declares_every_registered_service() -> None:
    """Undeclared services are invisible in the HA service picker.

    `clear_memory` and `reload_tools` were registered in code but missing from
    services.yaml, so the UI offered no way to call them and the `store` field
    never appeared.
    """
    import yaml

    from custom_components.smartchain import SERVICE_ANALYZE_IMAGE, SERVICE_ASK
    from custom_components.smartchain.const import (
        SERVICE_CLEAR_MEMORY,
        SERVICE_REINDEX_ENTITIES,
        SERVICE_RELOAD_TOOLS,
    )

    path = Path(__file__).parent.parent / "custom_components" / "smartchain" / "services.yaml"
    declared = yaml.safe_load(path.read_text())

    assert set(declared) == {
        SERVICE_ASK,
        SERVICE_ANALYZE_IMAGE,
        SERVICE_CLEAR_MEMORY,
        SERVICE_RELOAD_TOOLS,
        SERVICE_REINDEX_ENTITIES,
    }
    assert set(declared[SERVICE_CLEAR_MEMORY]["fields"]) == {"kind", "agent_id", "store"}
    assert declared[SERVICE_CLEAR_MEMORY]["fields"]["kind"]["selector"]["select"]["options"] == [
        "any",
        "conversation",
        "logbook",
    ]
    assert "fields" not in declared[SERVICE_RELOAD_TOOLS]
    assert set(declared[SERVICE_REINDEX_ENTITIES]["fields"]) == {"store", "full"}
