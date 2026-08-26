"""Tests for the service action executor."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

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


async def test_service_call_that_never_returns_becomes_a_message(hass: HomeAssistant) -> None:
    """`blocking=True` with no budget hangs the whole conversation turn.

    HA core has no `SERVICE_CALL_LIMIT` any more, so a service that waits —
    a script, a `wait_for_trigger`, an unreachable device — held the turn open
    for as long as it liked. REST already had a budget; this is the same one,
    and going over it is a sentence the model can read, not a raised exception.
    """
    action = ServiceAction(domain="light", service="turn_on", timeout=0)

    async def _never(*args, **kwargs):
        await asyncio.sleep(3600)

    with patch(_PATCH_TARGET, new_callable=AsyncMock, side_effect=_never):
        result = await execute_service(hass, action, {})

    # The configured budget, not a constant — a hardcoded deadline here would
    # be a second, invisible timeout beside the one the user wrote down.
    assert result == "Error: light.turn_on timed out after 0s"


async def test_service_timeout_defaults_to_the_shared_budget() -> None:
    """A hand-built action gets the budget without having to ask for it."""
    assert ServiceAction(domain="light", service="turn_on").timeout == ACTION_DEFAULT_TIMEOUT


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
