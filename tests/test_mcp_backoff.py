"""The MCP reconnect backoff, measured on the constants production actually uses.

`test_connect_failure_triggers_reconnect_attempt` in test_mcp_manager.py asserts
only that a second attempt happens, on delays overwritten to 0.01/0.05. That
leaves the shape of the backoff unwatched: replacing the doubling with a flat
`delay = self._initial_delay` keeps every MCP test green while, in production, a
mistyped URL retries once a second forever and writes a `LOGGER.exception` each
time — a log growing thirty times faster than the documented 1 s -> 30 s ramp
promises.

These tests therefore leave `_initial_delay` / `_max_delay` at their module
defaults and collect the argument of every `asyncio.sleep` the server task
performs.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import (
    MCP_RECONNECT_INITIAL_DELAY,
    MCP_RECONNECT_MAX_DELAY,
)
from custom_components.smartchain.tools.mcp.config import StdioConfig
from custom_components.smartchain.tools.mcp.manager import MCPManager
from custom_components.smartchain.tools.model import ToolRegistry

TASK_NAME = "smartchain_mcp_fs"


class _SleepRecorder:
    """Replaces asyncio.sleep, recording only the MCP server task's own waits.

    Sleeps from anywhere else (Home Assistant's own background work, and the
    manager's `wait_idle` helper) are delegated to the real sleep untouched, so
    the recorded sequence is exactly the backoff ramp.
    """

    def __init__(self, stop_after: int | None = None) -> None:
        self.delays: list[float] = []
        self._stop_after = stop_after
        self._real = asyncio.sleep

    async def __call__(self, delay, *args, **kwargs):
        task = asyncio.current_task()
        if task is not None and task.get_name() == TASK_NAME and delay != 60:
            self.delays.append(delay)
            if self._stop_after is not None and len(self.delays) >= self._stop_after:
                # Ends the retry loop the way a shutdown would.
                raise asyncio.CancelledError
            return await self._real(0)
        return await self._real(delay, *args, **kwargs)


def _always_failing_client_class():
    """Patch MCPClient so every connect() raises."""

    def make_instance(*args, **kwargs):
        inst = AsyncMock()
        inst.connect = AsyncMock(side_effect=RuntimeError("boom"))
        inst.close = AsyncMock()
        return inst

    patcher = patch("custom_components.smartchain.tools.mcp.manager.MCPClient")
    cls = patcher.start()
    cls.side_effect = make_instance
    return patcher, cls


async def test_retry_delay_doubles_and_saturates_at_the_maximum(hass: HomeAssistant) -> None:
    """Seven consecutive failures wait 1, 2, 4, 8, 16, 30, 30 seconds."""
    patcher, _cls = _always_failing_client_class()
    recorder = _SleepRecorder(stop_after=7)
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        with patch("asyncio.sleep", recorder):
            await mgr.start()
            task = mgr._servers["fs"].task
            assert task is not None
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
    finally:
        patcher.stop()

    assert recorder.delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    assert recorder.delays[0] == MCP_RECONNECT_INITIAL_DELAY
    assert max(recorder.delays) == MCP_RECONNECT_MAX_DELAY
    await mgr.stop()


async def test_retry_delay_is_bounded_by_the_maximum_forever(hass: HomeAssistant) -> None:
    """The ramp never climbs past the cap, however long the server stays down."""
    patcher, _cls = _always_failing_client_class()
    recorder = _SleepRecorder(stop_after=20)
    try:
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        with patch("asyncio.sleep", recorder):
            await mgr.start()
            task = mgr._servers["fs"].task
            assert task is not None
            await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
    finally:
        patcher.stop()

    assert len(recorder.delays) == 20
    assert all(d <= MCP_RECONNECT_MAX_DELAY for d in recorder.delays)
    # Once saturated it stays saturated — no drift back down, no climb past 30.
    assert recorder.delays[5:] == [MCP_RECONNECT_MAX_DELAY] * 15
    await mgr.stop()


async def test_backoff_restarts_from_the_initial_delay_after_a_working_connection(
    hass: HomeAssistant,
) -> None:
    """A server that connected, then dropped, retries from 1 s — not from where it left off.

    Without the reset a server that flapped early in the day would, hours later,
    take its full 30 s cap to come back from a one-second blip.
    """
    connects = {"n": 0}
    fail_until = {"n": 2}

    async def connect_side_effect():
        connects["n"] += 1
        if connects["n"] <= fail_until["n"]:
            raise RuntimeError("boom")

    def make_instance(*args, **kwargs):
        inst = AsyncMock()
        inst.connect = AsyncMock(side_effect=connect_side_effect)
        inst.list_tools = AsyncMock(return_value=[])
        inst.call_tool = AsyncMock(side_effect=RuntimeError("transport gone"))
        inst.close = AsyncMock()
        return inst

    recorder = _SleepRecorder()
    with patch("custom_components.smartchain.tools.mcp.manager.MCPClient") as cls:
        cls.side_effect = make_instance
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        with patch("asyncio.sleep", recorder):
            await mgr.start()
            await mgr.wait_idle(timeout=5.0)
            assert mgr._servers["fs"].client is not None
            first_ramp = list(recorder.delays)

            # The live connection dies mid-call: manager tears it down and
            # schedules a fresh connect task, whose first attempt fails once more.
            fail_until["n"] = connects["n"] + 1
            await mgr.call_tool("fs", "x", {})
            await mgr.wait_idle(timeout=5.0)
            second_ramp = recorder.delays[len(first_ramp) :]
        await mgr.stop()

    assert first_ramp == [1.0, 2.0]
    assert second_ramp, "the reconnect task never retried"
    assert second_ramp[0] == MCP_RECONNECT_INITIAL_DELAY


@pytest.mark.parametrize("failures", [1, 3])
async def test_every_failed_attempt_waits_before_the_next(
    hass: HomeAssistant, failures: int
) -> None:
    """There is exactly one wait per failure — no attempt is retried instantly."""
    connects = {"n": 0}

    async def connect_side_effect():
        connects["n"] += 1
        if connects["n"] <= failures:
            raise RuntimeError("boom")

    def make_instance(*args, **kwargs):
        inst = AsyncMock()
        inst.connect = AsyncMock(side_effect=connect_side_effect)
        inst.list_tools = AsyncMock(return_value=[])
        inst.close = AsyncMock()
        return inst

    recorder = _SleepRecorder()
    with patch("custom_components.smartchain.tools.mcp.manager.MCPClient") as cls:
        cls.side_effect = make_instance
        registry = ToolRegistry()
        mgr = MCPManager(hass, registry)
        mgr.configure([StdioConfig(name="fs", command="npx")])
        with patch("asyncio.sleep", recorder):
            await mgr.start()
            await mgr.wait_idle(timeout=5.0)
        await mgr.stop()

    assert len(recorder.delays) == failures
    assert connects["n"] == failures + 1
