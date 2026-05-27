"""Tests for the tool dispatcher."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.dispatcher import dispatch
from custom_components.smartchain.tools.model import (
    CustomTool,
    TemplateAction,
)


@pytest.fixture
def ping_tool() -> CustomTool:
    return CustomTool(
        name="ping",
        description="pong",
        parameters={
            "type": "object",
            "properties": {"loud": {"type": "boolean"}},
            "required": ["loud"],
        },
        action=TemplateAction(value_template="{{ 'PONG' if loud else 'pong' }}"),
    )


async def test_dispatch_validates_args(hass: HomeAssistant, ping_tool: CustomTool) -> None:
    """Missing required arg produces a validation-error string for the LLM."""
    result = await dispatch(hass, ping_tool, {})
    assert "Invalid arguments" in result


async def test_dispatch_executes_template(hass: HomeAssistant, ping_tool: CustomTool) -> None:
    """Valid args route to the template executor."""
    result = await dispatch(hass, ping_tool, {"loud": True})
    assert result == "PONG"


async def test_dispatch_wraps_executor_exception(
    hass: HomeAssistant, ping_tool: CustomTool
) -> None:
    """An exception inside an action becomes a generic LLM-readable error."""
    with patch(
        "custom_components.smartchain.tools.dispatcher.execute_template",
        side_effect=RuntimeError("boom"),
    ):
        result = await dispatch(hass, ping_tool, {"loud": True})
    assert "Tool execution failed" in result
