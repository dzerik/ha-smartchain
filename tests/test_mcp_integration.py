"""End-to-end: YAML -> MCPManager -> discovered tool -> dispatcher -> result."""

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
from custom_components.smartchain.tools.model import MCPAction

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
def fake_mcp_client_class():
    """Patch MCPClient at the manager-import site."""
    with patch("custom_components.smartchain.tools.mcp.manager.MCPClient") as cls:
        instance = AsyncMock()
        instance.list_tools = AsyncMock(
            return_value=[
                {
                    "name": "echo",
                    "description": "Echo the input",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"msg": {"type": "string"}},
                        "required": ["msg"],
                    },
                }
            ]
        )
        instance.call_tool = AsyncMock(return_value="hi from MCP")
        instance.close = AsyncMock()
        cls.return_value = instance
        yield cls, instance


async def test_yaml_mcp_server_becomes_callable_tool(
    hass: HomeAssistant,
    mock_llm_client,
    tmp_path_factory,
    fake_mcp_client_class,
) -> None:
    """YAML with an MCP server lands tools in the registry; dispatch succeeds."""
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text(
        "tools: []\n"
        "mcp_servers:\n"
        "  - name: echo\n"
        "    transport: stdio\n"
        "    command: echo\n"
        "    args: ['ok']\n"
    )
    hass.config.config_dir = str(cdir)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await hass.data[DOMAIN]["mcp_manager"].wait_idle()

    registry = hass.data[DOMAIN]["tools"]
    tool = registry.get("echo__echo")
    assert tool is not None
    assert isinstance(tool.action, MCPAction)
    assert tool.action.server == "echo"
    assert tool.action.tool_name == "echo"

    # And dispatch goes all the way through.
    from custom_components.smartchain.tools.dispatcher import dispatch

    result = await dispatch(hass, tool, {"msg": "hello"})
    assert result == "hi from MCP"
