"""Exercise actual SDK contracts; mocks of ClientSession hide MCP 2 API changes."""

import asyncio
import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.metadata import version
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from custom_components.smartchain.tools.mcp import client as module
from custom_components.smartchain.tools.mcp.config import HTTPConfig, StdioConfig


async def test_real_sdk_tool_schema_and_error_flag():
    """The SDK's Python fields changed; its JSON aliases stayed the same."""
    schema = {"type": "object", "properties": {"message": {"type": "string"}}}
    session = AsyncMock()
    session.list_tools.return_value = ListToolsResult(
        tools=[Tool(name="echo", description="Echo a message", inputSchema=schema)]
    )
    session.call_tool.return_value = CallToolResult(
        content=[TextContent(type="text", text="rejected")], isError=True
    )
    client = module.MCPClient(StdioConfig(name="test", command=sys.executable))
    client._session = session

    tools = await client.list_tools()
    assert tools[0]["inputSchema"] == schema
    assert await client.call_tool("echo", {}) == "Tool execution failed: rejected"


async def test_real_stdio_server_round_trip(tmp_path):
    """Initialize, discover, call, ping and close using a real SDK server process."""
    script = tmp_path / "mcp_server.py"
    script.write_text(
        "try:\n"
        "    from mcp.server import MCPServer as Server\n"
        "except ImportError:\n"
        "    from mcp.server.fastmcp import FastMCP as Server\n"
        "server = Server('compatibility-test')\n"
        "@server.tool()\n"
        "def echo(message: str) -> str:\n"
        "    return message\n"
        "server.run(transport='stdio')\n"
    )
    client = module.MCPClient(
        StdioConfig(
            name="test",
            command=sys.executable,
            args=[str(script)],
            env={"PYTHONPATH": os.environ.get("PYTHONPATH", "")},
        )
    )
    async with asyncio.timeout(15):
        try:
            await client.connect()
            tools = await client.list_tools()
            assert [tool["name"] for tool in tools] == ["echo"]
            assert tools[0]["inputSchema"]["properties"]["message"]["type"] == "string"
            assert await client.call_tool("echo", {"message": "hello"}) == "hello"
            await client.ping()
        finally:
            await client.close()
    assert client._session is None


@pytest.mark.parametrize("verify_ssl", [True, False])
async def test_modern_http_transport_preserves_settings_and_closes_client(monkeypatch, verify_ssl):
    """MCP 2 receives a configured httpx2 client rather than old transport kwargs."""
    if version("mcp").split(".")[0] == "1":
        pytest.skip("MCP 2 transport contract")
    import httpx2

    clients = []
    streams = (object(), object())

    @asynccontextmanager
    async def transport(url, *, http_client):
        assert url == "https://example.com/mcp"
        assert isinstance(http_client, httpx2.AsyncClient)
        assert http_client.headers["authorization"] == "Bearer test-token"
        assert http_client.timeout.connect == 17
        assert http_client.timeout.read == 300
        assert http_client._transport._pool._ssl_context.check_hostname is verify_ssl
        clients.append(http_client)
        yield streams

    monkeypatch.setattr(module, "streamable_http_client", transport, raising=False)
    config = HTTPConfig(
        name="test",
        url="https://example.com/mcp",
        headers={"Authorization": "Bearer test-token"},
        timeout=17,
        verify_ssl=verify_ssl,
    )
    async with AsyncExitStack() as stack:
        assert await module.MCPClient(config)._open_transport(stack) == streams
        assert not clients[0].is_closed
    assert clients[0].is_closed
