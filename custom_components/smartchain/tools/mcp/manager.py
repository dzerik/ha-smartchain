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
    RESERVED_TOOL_NAMES,
)
from ..model import CustomTool, MCPAction, ToolRegistry
from .client import MCPClient
from .config import MCPServerConfig
from .naming import filter_tools, resolve_tool_name

LOGGER = logging.getLogger(__name__)

# How often a connected server is asked to prove it is still there. Lives here
# rather than in `const.py` because it is a detail of this loop and nothing else
# reads it. One minute is the interval the hold-loop already slept at; the
# difference is that the wakeup now costs a ping instead of nothing.
MCP_HEALTH_CHECK_INTERVAL = 60.0  # seconds


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
        self._health_interval = MCP_HEALTH_CHECK_INTERVAL
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

    def _lifecycle_lock(self) -> asyncio.Lock:
        """The lock every MCP lifecycle transition takes — deliberately the shared one.

        `_rebuild_lock` is what `_reload_registry` and `async_unload_entry`
        hold while they stop this manager, `configure()` it with a new server
        table and start it again. A reconnect is the same kind of transition,
        reached from a tool call — i.e. from an LLM turn, with no relation to
        the rebuild in flight — so it has to queue behind the same lock rather
        than a private one, or a relaunched `_run_server` finds its own server
        name gone from a `_servers` dict that was replaced underneath it.

        Taken by `_reconnect_server` and by the publish step of `_run_server`.
        **Never** by `start()` or `stop()`: their callers already hold it, and
        `asyncio.Lock` is not re-entrant.

        Imported inside the function because the package `__init__` imports this
        module; and resolved through `hass` rather than an instance attribute so
        the lock belongs to the running loop, as `_rebuild_lock` explains.
        """
        from ... import _rebuild_lock

        return _rebuild_lock(self.hass)

    async def stop(self) -> None:
        """Cancel all server tasks, await them, then close clients and deregister tools.

        Callers hold `_lifecycle_lock`; this must not take it itself.
        """
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
        state = self._servers.get(name)
        if state is None:
            # A rebuild replaced `_servers` between this task being scheduled
            # and its first line. Nothing to connect to; the new table's own
            # tasks own whatever is configured now.
            LOGGER.debug("MCP server %s is no longer configured; connect task exiting", name)
            return
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

            async with self._lifecycle_lock():
                # Re-check what the two awaits above could have changed: a stop,
                # or a rebuild that replaced the server table while we connected.
                if self._stopped or self._servers.get(name) is not state:
                    await self._close_quietly(client, name)
                    return
                state.client = client
                self._register_tools(state, tools)
            LOGGER.info("MCP server %s connected; %d tools registered", name, len(tools))
            # A working connection resets the ramp. The task used to *end* here
            # and a reconnect started a fresh one with a fresh `delay`; now the
            # loop below can bring us back round to a retry, so the reset has to
            # be written down.
            delay = self._initial_delay
            if not await self._hold_connection(name, state, client):
                return
            # The session stopped answering. Tear it down here rather than
            # through `_reconnect_server`: that one cancels this very task and
            # awaits it, which from inside this task is a deadlock.
            LOGGER.warning("MCP server %s stopped answering; reconnecting", name)
            async with self._lifecycle_lock():
                if (
                    self._stopped
                    or self._servers.get(name) is not state
                    or state.client is not client
                ):
                    # A rebuild, a stop, or a failing tool call got there first;
                    # whatever replaced this session owns it now.
                    return
                await self._close_quietly(client, name)
                state.client = None
                self._unregister_tools(state)

    async def _hold_connection(self, name: str, state: _ServerState, client: MCPClient) -> bool:
        """Watch a live session. True if it was lost, False if this task should exit.

        Without this the task simply slept until cancelled: a server that died
        after a successful handshake kept its `state.client` and its entry in
        the `ToolRegistry`, so every `bind_tools` still offered the model tools
        that could only fail. The exception path in `call_tool` was the sole
        route back — a reconnect that costs the user a tool call to discover.
        """
        while not self._stopped:
            try:
                await asyncio.sleep(self._health_interval)
            except asyncio.CancelledError:
                return False
            if self._stopped or self._servers.get(name) is not state or state.client is not client:
                return False
            if not await self._is_alive(client, name):
                return True
        return False

    async def _is_alive(self, client: MCPClient, name: str) -> bool:
        """One MCP `ping` round-trip, bounded by the same budget a tool call gets.

        A round-trip and not an attribute check: a stdio server whose process
        has exited, and an HTTP peer that has stopped answering, both leave a
        perfectly ordinary-looking client object behind. A ping that hangs is a
        dead connection too — that is what the timeout is for.
        """
        try:
            async with asyncio.timeout(self._call_timeout):
                await client.ping()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            LOGGER.warning(
                "MCP server %s did not answer a liveness ping within %ss",
                name,
                self._call_timeout,
            )
            return False
        except Exception as err:  # noqa: BLE001
            LOGGER.warning("MCP server %s failed its liveness ping: %s", name, err)
            return False
        return True

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
            # The third source of tool names, held to the same rule as
            # tools.yaml (`loader.py`) and the panel (`config_flow`). The
            # collision check below cannot stand in for it: the built-ins are
            # attached at bind time and are never in the `ToolRegistry`, so with
            # `prefix: ""` a server's `search_memory` would sail past it and
            # reach `bind_tools` beside the built-in of the same name.
            if registry_name in RESERVED_TOOL_NAMES:
                LOGGER.error(
                    "MCP server %s advertises tool %s, which resolves to the reserved "
                    "built-in name %s; skipping it. Set a prefix for this server to "
                    "expose the tool under a name of its own.",
                    cfg.name,
                    t["name"],
                    registry_name,
                )
                continue
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
                        # A mirror of the bound `call_tool` enforces, not a
                        # per-tool knob: nothing reads this field back, and no
                        # YAML key sets it. It exists so the tool inventory and
                        # the websocket API can show the budget in force, so it
                        # must never carry a number `call_tool` would not honour.
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
        # Bound to the client the call is made against, so the reconnect below
        # can tell "the session I used died" from "someone already replaced it".
        client = state.client if state is not None else None
        if state is None or client is None:
            return f"Error: MCP server {server} is unavailable"
        try:
            async with asyncio.timeout(self._call_timeout):
                return await client.call_tool(tool_name, arguments)
        except TimeoutError:
            LOGGER.warning("MCP call %s:%s timed out", server, tool_name)
            return "Error: MCP call timed out"
        except Exception:  # noqa: BLE001
            LOGGER.exception("MCP call %s:%s failed; triggering reconnect", server, tool_name)
            await self._reconnect_server(server, client=client)
            return f"Error: MCP server {server} is unavailable"

    async def _reconnect_server(self, name: str, *, client: MCPClient | None = None) -> None:
        """Tear down one server's session and re-schedule its connect task.

        `client` is the session the caller found dead. Under the lock it is
        compared against the live one by identity: if they differ, another
        failing call or a rebuild has already replaced the session and this
        pass must do nothing — running it anyway would close a connection that
        never failed and, worse, deregister the tools that replaced ours while
        `registered_names` still named them.
        """
        state = self._servers.get(name)
        if state is None or self._stopped:
            return
        if client is None:
            client = state.client
        async with self._lifecycle_lock():
            state = self._servers.get(name)
            if state is None or self._stopped:
                return
            if state.client is not client:
                LOGGER.debug(
                    "MCP server %s was already reconnected by another caller; skipping", name
                )
                return
            if state.client is not None:
                await self._close_quietly(state.client, name)
                state.client = None
            self._unregister_tools(state)
            if state.task is not None and not state.task.done():
                state.task.cancel()
                try:
                    await state.task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
                # Awaiting the cancelled task is the second yield point; the
                # server table may be a different one by now.
                if self._stopped or self._servers.get(name) is not state:
                    return
            if state.config.enabled:
                state.task = self.hass.async_create_background_task(
                    self._run_server(name), name=f"smartchain_mcp_{name}"
                )

    async def _close_quietly(self, client: MCPClient, name: str) -> None:
        """Close a client, logging rather than raising.

        A close that fails is not a reason to abandon the teardown that follows
        it — the registry bookkeeping and the relaunch still have to happen, or
        a server that errors on shutdown keeps its tools bound forever.
        """
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            LOGGER.exception("Error closing MCP client for %s", name)
