"""A handshake that is cancelled takes its transport down with it.

`connect()` builds an `AsyncExitStack`, opens the transport into it, enters a
`ClientSession`, and only then — after `initialize()` returns — hands the stack
to `self._exit_stack`. Cancelled anywhere before that last line, the stack is
lost with the frame: `self._exit_stack` is still `None`, so a later `close()`
finds nothing to close, and for a stdio server the child process outlives the
integration that spawned it.

That window is not hypothetical. `initialize()` waits for the server's reply,
and a reload or an unload cancels the connect task while it waits. The manager
closes the client it was building (`test_mcp_stop_closes_every_client.py`), but
that close can only work if `connect()` has left something behind to close —
otherwise the manager's guarantee is true of the mock and false of the process
table.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.smartchain.tools.mcp.client import MCPClient
from custom_components.smartchain.tools.mcp.config import StdioConfig


class _RecordingCM:
    """An async CM that writes its own name into `log` on enter and exit."""

    def __init__(self, log: list[str], label: str, value):
        self._log = log
        self._label = label
        self._value = value

    async def __aenter__(self):
        self._log.append(f"enter {self._label}")
        return self._value

    async def __aexit__(self, *exc_info) -> bool:
        self._log.append(f"exit {self._label}")
        return False


async def test_a_cancelled_initialize_closes_the_transport() -> None:
    """Cancel the connect while the server has not answered `initialize` yet."""
    log: list[str] = []
    reached_initialize = asyncio.Event()

    session = AsyncMock()

    async def never_answers():
        reached_initialize.set()
        await asyncio.Event().wait()

    session.initialize = AsyncMock(side_effect=never_answers)

    def fake_stdio_client(params):
        return _RecordingCM(log, "transport", ("read", "write"))

    def fake_session_class(*streams):
        return _RecordingCM(log, "session", session)

    with (
        patch(
            "custom_components.smartchain.tools.mcp.client.stdio_client",
            side_effect=fake_stdio_client,
        ),
        patch(
            "custom_components.smartchain.tools.mcp.client.ClientSession",
            side_effect=fake_session_class,
        ),
    ):
        client = MCPClient(StdioConfig(name="fs", command="npx"))
        task = asyncio.create_task(client.connect())
        await asyncio.wait_for(reached_initialize.wait(), timeout=3.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert "exit transport" in log, (
        f"the transport was left open when the handshake was cancelled: {log}"
    )
    assert "exit session" in log, (
        f"the session was left open when the handshake was cancelled: {log}"
    )
    # And nothing was published, so a later close() is correctly a no-op.
    assert client._exit_stack is None
    assert client._session is None


async def test_a_failed_initialize_still_closes_the_transport() -> None:
    """The behaviour that already worked, pinned so the cancellation fix cannot cost it."""
    log: list[str] = []
    session = AsyncMock()
    session.initialize = AsyncMock(side_effect=RuntimeError("handshake refused"))

    with (
        patch(
            "custom_components.smartchain.tools.mcp.client.stdio_client",
            side_effect=lambda params: _RecordingCM(log, "transport", ("read", "write")),
        ),
        patch(
            "custom_components.smartchain.tools.mcp.client.ClientSession",
            side_effect=lambda *streams: _RecordingCM(log, "session", session),
        ),
    ):
        client = MCPClient(StdioConfig(name="fs", command="npx"))
        with pytest.raises(RuntimeError, match="handshake refused"):
            await client.connect()

    assert log == ["enter transport", "enter session", "exit session", "exit transport"], log
    assert client._exit_stack is None
