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


async def test_dispatch_reports_broken_schema_instead_of_killing_the_turn(
    hass: HomeAssistant,
) -> None:
    """A tool whose own `parameters` is not a legal JSON Schema answers the model.

    `jsonschema.validate` checks the *schema* before the instance and raises
    `SchemaError`, which is NOT a subclass of `ValidationError`. Unhandled it
    escapes `dispatch` and takes the whole conversation turn with it, so one
    `type: str` typo in tools.yaml costs the user the conversation rather than
    one tool call. The message names the offending value so the model — and the
    log — can say what is wrong.
    """
    broken = CustomTool(
        name="weather",
        description="typo in its own schema",
        parameters={"type": "object", "properties": {"city": {"type": "nosuchtype"}}},
        action=TemplateAction(value_template="never reached"),
    )

    result = await dispatch(hass, broken, {"city": "Moscow"})

    assert "Invalid arguments" in result
    assert "nosuchtype" in result


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
