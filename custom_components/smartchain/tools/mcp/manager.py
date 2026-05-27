"""MCPManager — owns the per-server connect tasks and the registry of MCP tools."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

from ...const import (
    MCP_CALL_TIMEOUT_DEFAULT,
    MCP_RECONNECT_INITIAL_DELAY,
    MCP_RECONNECT_MAX_DELAY,
)
from ..model import CustomTool, MCPAction, ToolRegistry
from .client import MCPClient
from .config import MCPServerConfig
from .naming import filter_tools, resolve_tool_name

LOGGER = logging.getLogger(__name__)


@dataclass
class _ServerState:
    """Live state for one configured MCP server."""

    config: MCPServerConfig
    client: MCPClient | None = None
    task: asyncio.Task | None = None
    registered_names: list[str] = field(default_factory=list)


class MCPManager:
    """Owns lifecycle for all configured MCP servers.

    Lifecycle:
      configure(...)  - record desired servers
      start()         - schedule connect-tasks (non-blocking)
      wait_idle()     - test helper; wait for all initial connect-tasks to settle
      stop()          - cancel tasks, close clients, deregister tools
      call_tool(...)  - facade used by execute_mcp
    """

    def __init__(self, hass: HomeAssistant, registry: ToolRegistry) -> None:
        self.hass = hass
        self.registry = registry
        self._servers: dict[str, _ServerState] = {}
        self._initial_delay = MCP_RECONNECT_INITIAL_DELAY
        self._max_delay = MCP_RECONNECT_MAX_DELAY
        self._call_timeout = MCP_CALL_TIMEOUT_DEFAULT
        self._stopped = False

    # ----- configuration & lifecycle -----

    def configure(self, servers: list[MCPServerConfig]) -> None:
        """Replace the configured server list (no connections changed yet)."""
        self._servers = {s.name: _ServerState(config=s) for s in servers}

    async def start(self) -> None:
        """Schedule a connect-task per enabled server."""
        self._stopped = False
        for name, state in self._servers.items():
            if not state.config.enabled:
                continue
            state.task = self.hass.async_create_background_task(
                self._run_server(name), name=f"smartchain_mcp_{name}"
            )

    async def wait_idle(self, timeout: float = 5.0) -> None:
        """Wait until every server's initial connect attempt has completed.

        Used by tests to avoid sleeping; in production the connect tasks keep
        running in the background and reconnect on failure.
        """
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            now = asyncio.get_running_loop().time()
            if now > deadline:
                return
            pending = [
                state.task
                for state in self._servers.values()
                if state.task is not None and not state.task.done() and state.client is None
            ]
            if not pending:
                return
            await asyncio.sleep(0.01)

    async def stop(self) -> None:
        """Cancel all server tasks, await them, then close clients and deregister tools."""
        self._stopped = True
        tasks = [s.task for s in self._servers.values() if s.task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for state in self._servers.values():
            state.task = None
            if state.client is not None:
                try:
                    await state.client.close()
                except Exception:  # noqa: BLE001
                    LOGGER.exception("Error closing MCP client for %s", state.config.name)
                state.client = None
            self._unregister_tools(state)

    # ----- per-server loop -----

    async def _run_server(self, name: str) -> None:
        state = self._servers[name]
        delay = self._initial_delay
        while not self._stopped:
            client = MCPClient(state.config)
            try:
                await client.connect()
                tools = await client.list_tools()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                LOGGER.exception(
                    "MCP server %s connect failed; retrying in %.1fs",
                    name,
                    delay,
                )
                try:
                    await client.close()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    return
                delay = min(delay * 2, self._max_delay)
                continue

            state.client = client
            self._register_tools(state, tools)
            LOGGER.info("MCP server %s connected; %d tools registered", name, len(tools))
            # Connection is open; hold the task alive until cancellation.
            try:
                while not self._stopped:
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                return

    # ----- registry bookkeeping -----

    def _register_tools(self, state: _ServerState, tools: list[dict[str, Any]]) -> None:
        cfg = state.config
        names = [t["name"] for t in tools]
        kept = set(filter_tools(names, cfg.include_tools, cfg.exclude_tools))
        registered: list[str] = []
        for t in tools:
            if t["name"] not in kept:
                continue
            registry_name = resolve_tool_name(cfg.name, cfg.prefix, t["name"])
            if self.registry.get(registry_name) is not None:
                LOGGER.error(
                    "MCP tool %s collides with an existing tool name; skipping",
                    registry_name,
                )
                continue
            self.registry.add(
                CustomTool(
                    name=registry_name,
                    description=t["description"],
                    parameters=t["inputSchema"],
                    action=MCPAction(
                        server=cfg.name,
                        tool_name=t["name"],
                        timeout=self._call_timeout,
                    ),
                )
            )
            registered.append(registry_name)
        state.registered_names = registered

    def _unregister_tools(self, state: _ServerState) -> None:
        if not state.registered_names:
            return
        to_remove = set(state.registered_names)
        kept = [t for t in self.registry.all() if t.name not in to_remove]
        self.registry.replace_all(kept)
        state.registered_names = []

    # ----- public call surface -----

    async def call_tool(self, server: str, tool_name: str, arguments: dict[str, Any]) -> str:
        state = self._servers.get(server)
        if state is None or state.client is None:
            return f"Error: MCP server {server} is unavailable"
        try:
            async with asyncio.timeout(self._call_timeout):
                return await state.client.call_tool(tool_name, arguments)
        except TimeoutError:
            LOGGER.warning("MCP call %s:%s timed out", server, tool_name)
            return "Error: MCP call timed out"
        except Exception:  # noqa: BLE001
            LOGGER.exception("MCP call %s:%s failed; triggering reconnect", server, tool_name)
            await self._reconnect_server(server)
            return f"Error: MCP server {server} is unavailable"

    async def _reconnect_server(self, name: str) -> None:
        """Tear down a server's state and re-schedule its connect task."""
        state = self._servers.get(name)
        if state is None or self._stopped:
            return
        if state.client is not None:
            try:
                await state.client.close()
            except Exception:  # noqa: BLE001
                LOGGER.exception("Error closing MCP client for %s during reconnect", name)
            state.client = None
        self._unregister_tools(state)
        if state.task is not None and not state.task.done():
            state.task.cancel()
            try:
                await state.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if not self._stopped and state.config.enabled:
            state.task = self.hass.async_create_background_task(
                self._run_server(name), name=f"smartchain_mcp_{name}"
            )
