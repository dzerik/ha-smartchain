"""Tests for the service action executor."""

import asyncio
import json
import logging
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.actions.service_action import execute_service
from custom_components.smartchain.tools.model import (
    ACTION_DEFAULT_TIMEOUT,
    ACTION_MAX_TIMEOUT,
    ServiceAction,
)

_PATCH_TARGET = "homeassistant.core.ServiceRegistry.async_call"


async def test_service_renders_data_templates_and_calls(hass: HomeAssistant) -> None:
    """Templates inside `data` and `target` are rendered with args before calling."""
    action = ServiceAction(
        domain="light",
        service="turn_on",
        target={"entity_id": "light.{{ area }}_main"},
        data={"brightness_pct": "{{ brightness }}"},
    )
    with patch(_PATCH_TARGET, new_callable=AsyncMock, return_value=None) as mock_call:
        result = await execute_service(hass, action, {"area": "kitchen", "brightness": 80})

    assert result == "OK"
    mock_call.assert_awaited_once()
    call_args = mock_call.call_args
    # When patching at class level, positional args are (self, domain, service)
    # but when the mock replaces the unbound method, self is included.
    pos = call_args.args
    # strip leading self if present (class-level patch passes self explicitly)
    domain, service = (pos[1], pos[2]) if len(pos) >= 3 else (pos[0], pos[1])
    assert (domain, service) == ("light", "turn_on")
    assert call_args.kwargs.get("blocking") is True
    assert call_args.kwargs.get("target") == {"entity_id": "light.kitchen_main"}


async def test_service_returns_response_as_json(hass: HomeAssistant) -> None:
    """When `response: true`, the service response is returned as JSON."""
    action = ServiceAction(
        domain="weather",
        service="get_forecasts",
        response=True,
    )
    fake_response = {"weather.home": {"forecast": [{"temperature": 20}]}}
    with patch(_PATCH_TARGET, new_callable=AsyncMock, return_value=fake_response):
        result = await execute_service(hass, action, {})

    assert json.loads(result) == fake_response


def _controllable_call() -> tuple[list[str], asyncio.Event, Any]:
    """A fake service handler that records whether it ran to the end.

    `marks` is the whole point: `started` alone means the handler was entered,
    `started, finished` means it completed, `started, cancelled` means someone
    killed it half way. The `release` event stands in for whatever the real
    handler is waiting on — a `delay`, a device, a `wait_for_trigger`.
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


async def test_service_call_that_never_returns_becomes_a_message(hass: HomeAssistant) -> None:
    """`blocking=True` with no budget hangs the whole conversation turn.

    HA core has no `SERVICE_CALL_LIMIT` any more, so a service that waits —
    a script, a `wait_for_trigger`, an unreachable device — held the turn open
    for as long as it liked. REST already had a budget; this is the same one,
    and going over it is a sentence the model can read, not a raised exception.

    The sentence says *started, no result yet* rather than *timed out*, because
    that is what now happens: see the test below.
    """
    action = ServiceAction(domain="light", service="turn_on", timeout=0)
    marks, release, handler = _controllable_call()

    with patch(_PATCH_TARGET, new_callable=AsyncMock, side_effect=handler):
        result = await execute_service(hass, action, {})
        release.set()
        await hass.async_block_till_done()

    # The configured budget, not a constant — a hardcoded deadline here would
    # be a second, invisible timeout beside the one the user wrote down.
    assert result == "Started light.turn_on; no result after 0s — it is still running."
    assert marks == ["started", "finished"]


async def test_a_service_past_its_budget_is_not_cancelled(hass: HomeAssistant) -> None:
    """The budget stops us WAITING; it must not stop the service RUNNING.

    Awaiting `hass.services.async_call` directly under `asyncio.timeout` made
    the deadline cancel the handler itself: the probe for this saw
    `['started', 'cancelled']` and no `finished`. Applied retroactively to
    every existing service and script tool, that turned a five-minute
    `script.morning_routine` into one that opens the curtains and stops half
    way — a worse bug than the hang it was fixing.
    """
    action = ServiceAction(domain="light", service="turn_on", timeout=0)
    marks, release, handler = _controllable_call()

    with patch(_PATCH_TARGET, new_callable=AsyncMock, side_effect=handler):
        await execute_service(hass, action, {})
        # The turn has moved on and the handler is still sitting in its wait.
        assert marks == ["started"]

        release.set()
        await hass.async_block_till_done()

    assert marks == ["started", "finished"]
    assert "cancelled" not in marks


async def test_service_timeout_defaults_to_the_shared_budget() -> None:
    """A hand-built action gets the budget without having to ask for it."""
    assert ServiceAction(domain="light", service="turn_on").timeout == ACTION_DEFAULT_TIMEOUT


async def test_a_failure_after_the_deadline_still_gets_recorded(
    hass: HomeAssistant, caplog
) -> None:
    """Letting the call outlive the turn moves its ending out of the model's sight.

    That is the price of not cancelling it, and it is only acceptable if the
    ending lands somewhere. Without the done-callback a service that failed
    after the budget would leave nothing at all behind — the exact trade this
    project has made nine times and regretted.
    """
    action = ServiceAction(domain="light", service="turn_on", timeout=0)
    release = asyncio.Event()

    async def _fails_late(*args, **kwargs):
        await release.wait()
        raise RuntimeError("device refused")

    with patch(_PATCH_TARGET, new_callable=AsyncMock, side_effect=_fails_late):
        result = await execute_service(hass, action, {})
        release.set()
        await hass.async_block_till_done()

    assert "still running" in result
    # At WARNING, not at debug: a line nobody's log level lets through is the
    # same silence, one indirection further away.
    loud = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING and "budget" in record.getMessage()
    ]
    assert loud == ["light.turn_on failed after its 0s budget: device refused"]


@pytest.mark.parametrize("budget", [3, 41, ACTION_MAX_TIMEOUT])
async def test_the_service_deadline_is_the_configured_number(
    hass: HomeAssistant, budget: int
) -> None:
    """The number handed to `asyncio.timeout` is `action.timeout` itself.

    `test_service_within_its_budget_is_not_cut_short` below claims this and
    does not prove it: replacing `asyncio.timeout(action.timeout)` with
    `asyncio.timeout(1.0)` left the whole file green, because every other test
    either finishes well inside a second or reports the budget from
    `action.timeout` in its message rather than from the deadline that fired.
    This one reads the argument, so any constant — 1.0 or otherwise — is red.

    The budgets are deliberately none of the constants a mutant would plausibly
    carry, and `1` is deliberately absent: `1 == 1.0`, so a `1`-second case
    would have let exactly the mutation in question through.
    """
    recorded: list[Any] = []
    real_timeout = asyncio.timeout

    def _record(delay):
        recorded.append(delay)
        return real_timeout(delay)

    action = ServiceAction(domain="light", service="turn_on", timeout=budget)
    marks, release, handler = _controllable_call()
    release.set()  # the call returns at once; only the deadline is under test

    with (
        patch(_PATCH_TARGET, new_callable=AsyncMock, side_effect=handler),
        patch("asyncio.timeout", _record),
    ):
        result = await execute_service(hass, action, {})

    assert result == "OK"
    assert marks == ["started", "finished"]
    assert budget in recorded, f"deadline was {recorded}, not {budget}"


async def test_service_within_its_budget_is_not_cut_short(hass: HomeAssistant) -> None:
    """The deadline is the configured one, not a constant baked into the executor.

    Paired with the test above: that one proves a budget exists, this one
    proves it is `action.timeout`. A hardcoded deadline passes the first test
    and fails this one, which is exactly the failure mode "the guarantee is
    named, the mechanism is wrong" produces.
    """
    action = ServiceAction(domain="light", service="turn_on", timeout=ACTION_MAX_TIMEOUT)

    async def _slow(*args, **kwargs):
        await asyncio.sleep(0.05)

    with patch(_PATCH_TARGET, new_callable=AsyncMock, side_effect=_slow):
        result = await execute_service(hass, action, {})

    assert result == "OK"
