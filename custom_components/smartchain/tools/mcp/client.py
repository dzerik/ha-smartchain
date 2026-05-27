"""Transport-agnostic wrapper over the mcp Python SDK."""

import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client

try:
    from mcp.client.streamable_http import streamablehttp_client
except ImportError:  # pragma: no cover — present in mcp>=1.6
    streamablehttp_client = None  # type: ignore[assignment]

from .config import HTTPConfig, MCPServerConfig, SSEConfig, StdioConfig

LOGGER = logging.getLogger(__name__)


class MCPClient:
    """Owns one live MCP ClientSession.

    Usage:
        client = MCPClient(cfg)
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("read_file", {"path": "/etc/hosts"})
        await client.close()
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    async def connect(self) -> None:
        """Open the transport and initialise the session."""
        stack = AsyncExitStack()
        try:
            streams = await self._open_transport(stack)
            session = await stack.enter_async_context(ClientSession(*streams))
            await session.initialize()
        except Exception:
            await stack.aclose()
            raise
        self._exit_stack = stack
        self._session = session

    async def _open_transport(self, stack: AsyncExitStack):
        cfg = self.config
        if isinstance(cfg, StdioConfig):
            params = StdioServerParameters(
                command=cfg.command,
                args=list(cfg.args),
                env=dict(cfg.env) or None,
            )
            return await stack.enter_async_context(stdio_client(params))
        if isinstance(cfg, SSEConfig):
            return await stack.enter_async_context(
                sse_client(
                    cfg.url,
                    headers=dict(cfg.headers) or None,
                    timeout=cfg.timeout,
                )
            )
        if isinstance(cfg, HTTPConfig):
            if streamablehttp_client is None:
                raise RuntimeError(
                    "Streamable HTTP transport is not available in the installed mcp SDK."
                )
            ctx = streamablehttp_client(
                cfg.url,
                headers=dict(cfg.headers) or None,
                timeout=cfg.timeout,
            )
            streams = await stack.enter_async_context(ctx)
            # streamablehttp_client returns (read, write, _) -- session needs only first two.
            return streams[0], streams[1]
        raise TypeError(f"unsupported MCP config type: {type(cfg).__name__}")

    async def list_tools(self) -> list[dict[str, Any]]:
        if self._session is None:
            raise RuntimeError(f"MCPClient({self.config.name}) is not connected")
        resp = await self._session.list_tools()
        out: list[dict[str, Any]] = []
        for tool in resp.tools:
            out.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema or {"type": "object", "properties": {}},
                }
            )
        return out

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if self._session is None:
            raise RuntimeError(f"MCPClient({self.config.name}) is not connected")
        resp = await self._session.call_tool(name, arguments)
        text_chunks: list[str] = []
        non_text = False
        for item in getattr(resp, "content", None) or []:
            if getattr(item, "type", None) == "text":
                text_chunks.append(item.text or "")
            else:
                non_text = True
        rendered = "\n".join(text_chunks) if text_chunks else ""
        if non_text and not text_chunks:
            rendered = "[non-text content]"
        elif non_text:
            rendered = rendered + "\n[non-text content]"
        if getattr(resp, "isError", False):
            return f"Tool execution failed: {rendered}"
        return rendered

    async def close(self) -> None:
        stack = self._exit_stack
        self._session = None
        self._exit_stack = None
        if stack is not None:
            await stack.aclose()
