"""Execute a service action — call a Home Assistant service with rendered args."""

import asyncio
import json
import logging
from functools import partial
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import template as template_helper

from ..model import ServiceAction

LOGGER = logging.getLogger(__name__)


def _log_late_outcome(label: str, budget: float, task: asyncio.Task[Any]) -> None:
    """Report how a call that outlived its budget ended.

    The model was already told "still running" and the turn is over, so this
    log is the only place the real outcome can land. A failure after the
    deadline that nobody records is exactly the "visible error replaced by a
    silent success" shape this integration keeps paying for.
    """
    if task.cancelled():
        LOGGER.warning("%s was cancelled after its %ss budget", label, budget)
        return
    err = task.exception()
    if err is not None:
        LOGGER.warning("%s failed after its %ss budget: %s", label, budget, err)
    else:
        LOGGER.info("%s finished after its %ss budget", label, budget)


def _render_value(value: Any, hass: HomeAssistant, args: dict[str, Any]) -> Any:
    """Render Jinja in string values; recurse into dicts and lists.

    A `Template` object is rendered as itself rather than falling through to
    the `return value` below. It should not get this far — nothing this
    integration writes into a subentry survives the guard in `storable` as an
    object — but the fallthrough was the quiet half of that bug: an
    unrendered `Template` passed straight into
    `hass.services.async_call(target=…)`, so the model's argument never
    reached the service and the call did nothing visible. A tool that silently
    targets nothing is worse than one that raises, and this costs one branch.
    """
    if isinstance(value, template_helper.Template):
        # Its source text, rendered against *this* `hass` — the same line the
        # `str` branch below takes — rather than trusting whichever hass the
        # object happens to have been constructed with.
        return template_helper.Template(value.template, hass).async_render(args, parse_result=False)
    if isinstance(value, str):
        if "{{" not in value and "{%" not in value:
            return value
        return template_helper.Template(value, hass).async_render(args, parse_result=False)
    if isinstance(value, dict):
        return {k: _render_value(v, hass, args) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_value(v, hass, args) for v in value]
    return value


async def execute_service(
    hass: HomeAssistant,
    action: ServiceAction,
    args: dict[str, Any],
) -> str:
    """Call the configured service and return a string LLM-tool result."""
    target = _render_value(action.target, hass, args) if action.target else None
    data = _render_value(action.data, hass, args) if action.data else None

    # `blocking=True` waits for the service to finish and Home Assistant core
    # no longer enforces a `SERVICE_CALL_LIMIT`, so without this budget a
    # service that waits — on a device, on a script, on a trigger — holds the
    # conversation turn open for as long as it likes.
    #
    # The budget bounds how long *we wait*. It must not bound how long the
    # *service runs*: those are two different promises and only the first one
    # was ever asked for. Awaiting `hass.services.async_call` directly under
    # `asyncio.timeout` conflated them — the deadline cancelled the handler
    # itself, so a five-minute `script.morning_routine` opened the curtains and
    # stopped half way. The call therefore gets its own task and the wait goes
    # through `asyncio.shield`: at the deadline the *await* is cancelled and
    # the task is not, so whatever the user set in motion runs to its end.
    #
    # `blocking=False` would also stop the waiting, and was rejected: it makes
    # `return_response` illegal in core, so every `response: true` tool would
    # break, and it would hide a `ServiceNotFound` or a bad argument that today
    # reaches the model within the budget.
    #
    # `asyncio.wait` rather than `asyncio.shield`, which is the obvious way to
    # write this: both leave the task alone when our wait is cancelled, but
    # 3.14's `shield` hands the task's later exception to the loop exception
    # handler, so a service that fails after its budget would print an
    # unhandled-error traceback beside the line we log deliberately below.
    call = hass.async_create_task(
        hass.services.async_call(
            action.domain,
            action.service,
            service_data=data,
            target=target,
            blocking=True,
            return_response=action.response,
        ),
        f"SmartChain tool service {action.domain}.{action.service}",
        eager_start=True,
    )
    try:
        async with asyncio.timeout(action.timeout):
            await asyncio.wait([call])
    except TimeoutError:
        LOGGER.warning(
            "Service %s.%s has not finished within %ss; it keeps running",
            action.domain,
            action.service,
            action.timeout,
        )
        # The task outlives this turn, so its outcome has nowhere else to go.
        # Without this the log is the only record — and a late failure would be
        # a silent one, which is the failure mode this file keeps hitting.
        call.add_done_callback(
            partial(_log_late_outcome, f"{action.domain}.{action.service}", action.timeout)
        )
        # Not "Error" and not "cancelled": neither is true. The model is told
        # exactly what happened so it can say so, or ask again later.
        return (
            f"Started {action.domain}.{action.service}; "
            f"no result after {action.timeout}s — it is still running."
        )

    # Outside the `try`, so that a service raising `TimeoutError` of its own —
    # a device that gave up — is reported as the failure it is rather than
    # swallowed by the branch above and described as still running.
    response = call.result()

    if action.response:
        return json.dumps(response, ensure_ascii=False, default=str)
    return "OK"
