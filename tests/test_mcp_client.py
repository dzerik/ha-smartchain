"""Tests for MCPClient — thin wrapper over the mcp SDK."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.smartchain.tools.mcp.client import MCPClient
from custom_components.smartchain.tools.mcp.config import StdioConfig


@pytest.fixture
def fake_session():
    """A fake mcp ClientSession with list_tools + call_tool mocked."""
    session = MagicMock()
    fake_tool = MagicMock()
    fake_tool.name = "read_file"
    fake_tool.description = "Read a file"
    fake_tool.inputSchema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    session.list_tools = AsyncMock(return_value=MagicMock(tools=[fake_tool]))
    session.call_tool = AsyncMock(
        return_value=MagicMock(
            isError=False,
            content=[MagicMock(type="text", text="file contents")],
        )
    )
    session.initialize = AsyncMock()
    return session


async def test_list_tools_returns_tool_dicts(fake_session) -> None:
    cfg = StdioConfig(name="fs", command="npx")
    client = MCPClient(cfg)
    client._session = fake_session

    tools = await client.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "read_file"
    assert tools[0]["description"] == "Read a file"
    assert tools[0]["inputSchema"] == {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }


async def test_call_tool_returns_text_content(fake_session) -> None:
    cfg = StdioConfig(name="fs", command="npx")
    client = MCPClient(cfg)
    client._session = fake_session

    result = await client.call_tool("read_file", {"path": "/etc/hosts"})
    assert result == "file contents"


async def test_call_tool_error_result_returns_error_string(fake_session) -> None:
    fake_session.call_tool.return_value = MagicMock(
        isError=True,
        content=[MagicMock(type="text", text="permission denied")],
    )
    cfg = StdioConfig(name="fs", command="npx")
    client = MCPClient(cfg)
    client._session = fake_session

    result = await client.call_tool("read_file", {"path": "/etc/shadow"})
    assert "Tool execution failed" in result


async def test_call_tool_non_text_content_becomes_placeholder(fake_session) -> None:
    fake_session.call_tool.return_value = MagicMock(
        isError=False,
        content=[MagicMock(type="image", data="...")],
    )
    cfg = StdioConfig(name="fs", command="npx")
    client = MCPClient(cfg)
    client._session = fake_session

    result = await client.call_tool("snap", {})
    assert "[non-text content]" in result


async def test_client_not_connected_call_tool_raises() -> None:
    cfg = StdioConfig(name="fs", command="npx")
    client = MCPClient(cfg)
    with pytest.raises(RuntimeError, match="not connected"):
        await client.call_tool("x", {})


async def test_connect_stdio_uses_stdio_client() -> None:
    """connect() routes to stdio_client for StdioConfig."""
    cfg = StdioConfig(name="fs", command="echo", args=["hi"])

    fake_streams = (MagicMock(), MagicMock())
    stdio_ctx = MagicMock()
    stdio_ctx.__aenter__ = AsyncMock(return_value=fake_streams)
    stdio_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_session = MagicMock()
    fake_session.initialize = AsyncMock()
    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=fake_session)
    session_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch(
            "custom_components.smartchain.tools.mcp.client.stdio_client",
            return_value=stdio_ctx,
        ),
        patch(
            "custom_components.smartchain.tools.mcp.client.ClientSession",
            return_value=session_ctx,
        ),
    ):
        client = MCPClient(cfg)
        await client.connect()
        assert client._session is fake_session
        await client.close()
