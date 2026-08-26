"""Execute a script action — call a Home Assistant `script.*` with variables."""

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import template as template_helper

from ..model import ScriptAction

LOGGER = logging.getLogger(__name__)


def _render_value(value: Any, hass: HomeAssistant, args: dict[str, Any]) -> Any:
    if isinstance(value, str) and ("{{" in value or "{%" in value):
        return template_helper.Template(value, hass).async_render(args, parse_result=False)
    if isinstance(value, dict):
        return {k: _render_value(v, hass, args) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_value(v, hass, args) for v in value]
    return value


async def execute_script(
    hass: HomeAssistant,
    action: ScriptAction,
    args: dict[str, Any],
) -> str:
    """Execute the script and return a string LLM-tool result."""
    script_name = action.script.split(".", 1)[1]
    variables = _render_value(action.variables, hass, args) if action.variables else {}

    # Calling `script.<id>` blocking means `wait=True`: the call returns only
    # when the sequence ends, so a `delay: 00:05:00` holds the conversation
    # turn for five minutes and a `wait_for_trigger` holds it until the trigger
    # fires. Same budget and same shape as the `service` and REST executors.
    try:
        async with asyncio.timeout(action.timeout):
            await hass.services.async_call(
                "script",
                script_name,
                variables,
                blocking=True,
                return_response=False,
            )
    except TimeoutError:
        LOGGER.warning("Script %s did not finish within %ss", action.script, action.timeout)
        return f"Error: {action.script} timed out after {action.timeout}s"
    return "OK"
