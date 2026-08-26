"""Tests for the script action executor."""

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.actions.script_action import execute_script
from custom_components.smartchain.tools.model import (
    ACTION_DEFAULT_TIMEOUT,
    ACTION_MAX_TIMEOUT,
    ScriptAction,
)

_PATCH_TARGET = "homeassistant.core.ServiceRegistry.async_call"


async def test_script_call_passes_rendered_variables(hass: HomeAssistant) -> None:
    """Variables go through template rendering before being passed to script."""
    action = ScriptAction(
        script="script.morning",
        variables={"name": "{{ user }}", "level": "5"},
    )
    with patch(_PATCH_TARGET, new_callable=AsyncMock, return_value=None) as mock_call:
        result = await execute_script(hass, action, {"user": "alice"})

    assert result == "OK"
    mock_call.assert_awaited_once()
    pos = mock_call.call_args.args
    # class-level patch: args are (self, domain, service, service_data)
    # or just (domain, service, service_data) depending on Python version
    if len(pos) >= 4:
        _self, domain, service, service_data = pos[:4]
    else:
        domain, service, service_data = pos[:3]
    assert (domain, service) == ("script", "morning")
    assert service_data == {"name": "alice", "level": "5"}
    assert mock_call.call_args.kwargs.get("blocking") is True
    assert mock_call.call_args.kwargs.get("return_response") is False


async def test_script_without_variables(hass: HomeAssistant) -> None:
    """A script with no variables passes an empty dict."""
    action = ScriptAction(script="script.cleanup")
    with patch(_PATCH_TARGET, new_callable=AsyncMock, return_value=None) as mock_call:
        await execute_script(hass, action, {})

    mock_call.assert_awaited_once()
    pos = mock_call.call_args.args
    if len(pos) >= 4:
        _self, domain, service, service_data = pos[:4]
    else:
        domain, service, service_data = pos[:3]
    assert (domain, service) == ("script", "cleanup")
    assert service_data == {}
    assert mock_call.call_args.kwargs.get("blocking") is True
    assert mock_call.call_args.kwargs.get("return_response") is False


def _controllable_call() -> tuple[list[str], asyncio.Event, Any]:
    """A fake `script.*` handler that records whether it ran to the end.

    See the twin in `test_tools_action_service.py`: `started` alone means the
    sequence was entered, `started, finished` that it completed, and
    `started, cancelled` that something killed it half way.
    """
    marks: list[str] = []
    release = asyncio.Event()

    async def _handler(*args, **kwargs):
        marks.append("started")
        try:
            await release.wait()
        except asyncio.CancelledError:
            marks.append("cancelled")
            raise
        marks.append("finished")

    return marks, release, _handler


async def test_script_that_never_returns_becomes_a_message(hass: HomeAssistant) -> None:
    """`script.<id>` is called with `wait=True`, so `delay` and `wait_for_trigger` block.

    The documented `script.morning_routine` with `delay: 00:05:00` held a
    conversation turn open for five minutes; with `wait_for_trigger`, forever.
    Past the budget the model is told, and the turn goes on — while the
    sequence itself carries on to its end.
    """
    action = ScriptAction(script="script.morning", timeout=0)
    marks, release, handler = _controllable_call()

    with patch(_PATCH_TARGET, new_callable=AsyncMock, side_effect=handler):
        result = await execute_script(hass, action, {})
        release.set()
        await hass.async_block_till_done()

    assert result == "Started script.morning; no result after 0s — it is still running."
    assert marks == ["started", "finished"]


async def test_a_script_past_its_budget_is_not_cancelled(hass: HomeAssistant) -> None:
    """The documented example is the exact case this protects.

    `script.morning_routine` with `delay: 00:05:00` is in USAGE.md, and under a
    30 s budget that cancelled the call it would open the curtains and stop.
    The deadline may end our wait; it may not end the user's sequence.
    """
    action = ScriptAction(script="script.morning_routine", timeout=0)
    marks, release, handler = _controllable_call()

    with patch(_PATCH_TARGET, new_callable=AsyncMock, side_effect=handler):
        await execute_script(hass, action, {})
        assert marks == ["started"]

        release.set()
        await hass.async_block_till_done()

    assert marks == ["started", "finished"]
    assert "cancelled" not in marks


async def test_script_timeout_defaults_to_the_shared_budget() -> None:
    """The default is the same one `service` uses — one budget, not two."""
    assert ScriptAction(script="script.morning").timeout == ACTION_DEFAULT_TIMEOUT


async def test_a_failure_after_the_deadline_still_gets_recorded(
    hass: HomeAssistant, caplog
) -> None:
    """The twin of the service test: a sequence that breaks after the budget
    has already been reported as "still running", so the log is the only place
    left for its ending to go."""
    action = ScriptAction(script="script.morning", timeout=0)
    release = asyncio.Event()

    async def _fails_late(*args, **kwargs):
        await release.wait()
        raise RuntimeError("step 3 blew up")

    with patch(_PATCH_TARGET, new_callable=AsyncMock, side_effect=_fails_late):
        result = await execute_script(hass, action, {})
        release.set()
        await hass.async_block_till_done()

    assert "still running" in result
    loud = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING and "budget" in record.getMessage()
    ]
    assert loud == ["script.morning failed after its 0s budget: step 3 blew up"]


@pytest.mark.parametrize("budget", [3, 41, ACTION_MAX_TIMEOUT])
async def test_the_script_deadline_is_the_configured_number(
    hass: HomeAssistant, budget: int
) -> None:
    """The number handed to `asyncio.timeout` is `action.timeout` itself.

    The twin of the service test, and for the same reason: the docstring below
    promised this and `asyncio.timeout(action.timeout)` -> `asyncio.timeout(1.0)`
    survived the whole file. `1` is left out of the budgets on purpose —
    `1 == 1.0` would have let that exact mutant through.
    """
    recorded: list[Any] = []
    real_timeout = asyncio.timeout

    def _record(delay):
        recorded.append(delay)
        return real_timeout(delay)

    action = ScriptAction(script="script.morning", timeout=budget)
    marks, release, handler = _controllable_call()
    release.set()

    with (
        patch(_PATCH_TARGET, new_callable=AsyncMock, side_effect=handler),
        patch("asyncio.timeout", _record),
    ):
        result = await execute_script(hass, action, {})

    assert result == "OK"
    assert marks == ["started", "finished"]
    assert budget in recorded, f"deadline was {recorded}, not {budget}"


async def test_script_within_its_budget_is_not_cut_short(hass: HomeAssistant) -> None:
    """The deadline is `action.timeout`, not a constant baked into the executor.

    Kept as the behavioural half; the argument itself is checked above.
    """
    action = ScriptAction(script="script.morning", timeout=ACTION_MAX_TIMEOUT)

    async def _slow(*args, **kwargs):
        await asyncio.sleep(0.05)

    with patch(_PATCH_TARGET, new_callable=AsyncMock, side_effect=_slow):
        result = await execute_script(hass, action, {})

    assert result == "OK"
