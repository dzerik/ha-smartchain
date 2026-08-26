"""Execute a script action — call a Home Assistant `script.*` with variables."""

import asyncio
import logging
from functools import partial
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import template as template_helper

from ..model import ScriptAction

LOGGER = logging.getLogger(__name__)


def _log_late_outcome(label: str, budget: float, task: asyncio.Task[Any]) -> None:
    """Report how a sequence that outlived its budget ended — see the twin in
    `service_action.py`. The model heard "still running"; this is where the
    ending goes, so that a late failure is not a silent one."""
    if task.cancelled():
        LOGGER.warning("%s was cancelled after its %ss budget", label, budget)
        return
    err = task.exception()
    if err is not None:
        LOGGER.warning("%s failed after its %ss budget: %s", label, budget, err)
    else:
        LOGGER.info("%s finished after its %ss budget", label, budget)


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
    # fires. Same budget and same shape as the `service` executor — including
    # the part that matters most here: the budget ends our *wait*, never the
    # user's *sequence*. `script.morning_routine` from USAGE.md is the exact
    # case; under a cancelling deadline it opened the curtains and stopped.
    # Giving the call its own task and waiting on it without cancelling is what
    # keeps the two apart — see the longer note in `service_action.py`,
    # including why this is `asyncio.wait` and not `asyncio.shield`.
    call = hass.async_create_task(
        hass.services.async_call(
            "script",
            script_name,
            variables,
            blocking=True,
            return_response=False,
        ),
        f"SmartChain tool script {action.script}",
        eager_start=True,
    )
    try:
        async with asyncio.timeout(action.timeout):
            await asyncio.wait([call])
    except TimeoutError:
        LOGGER.warning(
            "Script %s has not finished within %ss; it keeps running",
            action.script,
            action.timeout,
        )
        call.add_done_callback(partial(_log_late_outcome, action.script, action.timeout))
        return f"Started {action.script}; no result after {action.timeout}s — it is still running."

    # Outside the `try`: a sequence that raised is a failure the model should
    # hear about, not a "still running".
    call.result()
    return "OK"
