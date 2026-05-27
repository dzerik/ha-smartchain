"""Tests that smartchain.reload_tools restarts MCP connections cleanly."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain import async_setup
from custom_components.smartchain.const import (
    DOMAIN,
    SERVICE_RELOAD_TOOLS,
)


@pytest.fixture
def tools_dir(hass: HomeAssistant, tmp_path_factory) -> Path:
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    hass.config.config_dir = str(cdir)
    return cdir / "smartchain"


async def test_reload_stops_then_starts_mcp_manager(hass: HomeAssistant, tools_dir: Path) -> None:
    (tools_dir / "tools.yaml").write_text("tools: []\nmcp_servers: []\n")
    await async_setup(hass, {})

    mgr = hass.data[DOMAIN]["mcp_manager"]
    with (
        patch.object(mgr, "stop", new_callable=AsyncMock) as stop,
        patch.object(mgr, "start", new_callable=AsyncMock) as start,
    ):
        await hass.services.async_call(DOMAIN, SERVICE_RELOAD_TOOLS, {}, blocking=True)

    stop.assert_awaited_once()
    start.assert_awaited_once()


async def test_reload_with_new_servers_reconfigures_manager(
    hass: HomeAssistant, tools_dir: Path
) -> None:
    (tools_dir / "tools.yaml").write_text("tools: []\nmcp_servers: []\n")
    await async_setup(hass, {})

    (tools_dir / "tools.yaml").write_text(
        "tools: []\nmcp_servers:\n  - name: fs\n    transport: stdio\n    command: npx\n"
    )

    mgr = hass.data[DOMAIN]["mcp_manager"]
    captured: dict = {}

    original_configure = mgr.configure

    def capture_configure(servers):
        captured["servers"] = servers
        return original_configure(servers)

    with (
        patch.object(mgr, "start", new_callable=AsyncMock),
        patch.object(mgr, "stop", new_callable=AsyncMock),
        patch.object(mgr, "configure", side_effect=capture_configure),
    ):
        await hass.services.async_call(DOMAIN, SERVICE_RELOAD_TOOLS, {}, blocking=True)

    assert len(captured["servers"]) == 1
    assert captured["servers"][0].name == "fs"
