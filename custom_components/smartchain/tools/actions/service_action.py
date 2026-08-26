"""Execute a service action — call a Home Assistant service with rendered args."""

import json
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import template as template_helper

from ..model import ServiceAction


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

    response = await hass.services.async_call(
        action.domain,
        action.service,
        service_data=data,
        target=target,
        blocking=True,
        return_response=action.response,
    )

    if action.response:
        return json.dumps(response, ensure_ascii=False, default=str)
    return "OK"
