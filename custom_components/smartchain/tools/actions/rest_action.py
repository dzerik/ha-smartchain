"""Execute a REST action — make an HTTP request with rendered URL/headers/payload."""

import asyncio
import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import template as template_helper
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..model import RESTAction

LOGGER = logging.getLogger(__name__)


def _render(value: Any, hass: HomeAssistant, args: dict[str, Any]) -> Any:
    if isinstance(value, str):
        if "{{" not in value and "{%" not in value:
            return value
        return template_helper.Template(value, hass).async_render(args, parse_result=False)
    if isinstance(value, dict):
        return {k: _render(v, hass, args) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, hass, args) for v in value]
    return value


async def execute_rest(
    hass: HomeAssistant,
    action: RESTAction,
    args: dict[str, Any],
) -> str:
    """Execute the REST call and return a string suitable for an LLM tool result."""
    url = _render(action.url, hass, args)
    headers = _render(action.headers, hass, args) if action.headers else None
    payload = _render(action.payload, hass, args) if action.payload else None

    session = async_get_clientsession(hass)
    try:
        async with asyncio.timeout(action.timeout):
            async with session.request(
                method=action.method,
                url=url,
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    LOGGER.warning(
                        "REST %s %s -> %s: %s", action.method, url, resp.status, body
                    )
                    return f"Error: HTTP {resp.status}"
                if action.response_format == "json":
                    return json.dumps(await resp.json(), ensure_ascii=False, default=str)
                return await resp.text()
    except TimeoutError:
        LOGGER.warning(
            "REST %s %s timed out after %ss", action.method, url, action.timeout
        )
        return "Error: request timed out"
