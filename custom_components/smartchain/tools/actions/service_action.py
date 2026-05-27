"""Execute a service action — call a Home Assistant service with rendered args."""

import json
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import template as template_helper

from ..model import ServiceAction


def _render_value(value: Any, hass: HomeAssistant, args: dict[str, Any]) -> Any:
    """Render Jinja in string values; recurse into dicts and lists."""
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
