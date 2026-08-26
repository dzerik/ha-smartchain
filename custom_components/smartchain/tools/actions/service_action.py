"""Execute a service action — call a Home Assistant service with rendered args."""

import asyncio
import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import template as template_helper

from ..model import ServiceAction

LOGGER = logging.getLogger(__name__)


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
    # conversation turn open for as long as it likes. Same shape as the REST
    # executor's `asyncio.timeout`, and like it, going over is a sentence the
    # model can read rather than an exception that ends the turn. The service
    # itself is cancelled at the deadline; whatever it already did, it did.
    try:
        async with asyncio.timeout(action.timeout):
            response = await hass.services.async_call(
                action.domain,
                action.service,
                service_data=data,
                target=target,
                blocking=True,
                return_response=action.response,
            )
    except TimeoutError:
        LOGGER.warning(
            "Service %s.%s did not finish within %ss",
            action.domain,
            action.service,
            action.timeout,
        )
        return f"Error: {action.domain}.{action.service} timed out after {action.timeout}s"

    if action.response:
        return json.dumps(response, ensure_ascii=False, default=str)
    return "OK"
