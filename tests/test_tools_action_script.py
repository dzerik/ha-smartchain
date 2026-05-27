"""Tests for the script action executor."""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.actions.script_action import execute_script
from custom_components.smartchain.tools.model import ScriptAction

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
