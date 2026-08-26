"""Validate args and dispatch a custom-tool call to the right action executor."""

import logging
from typing import Any

import jsonschema
from homeassistant.core import HomeAssistant

from .actions.mcp_action import execute_mcp
from .actions.rest_action import execute_rest
from .actions.script_action import execute_script
from .actions.service_action import execute_service
from .actions.template_action import execute_template
from .model import (
    CustomTool,
    MCPAction,
    RESTAction,
    ScriptAction,
    ServiceAction,
    TemplateAction,
)

LOGGER = logging.getLogger(__name__)


async def dispatch(
    hass: HomeAssistant,
    tool: CustomTool,
    args: dict[str, Any],
) -> str:
    """Validate args against the tool's JSON schema and run its action."""
    try:
        jsonschema.validate(instance=args, schema=tool.parameters)
    except jsonschema.SchemaError as err:
        # `jsonschema.validate` checks the *schema* before the instance, and
        # `SchemaError` is NOT a subclass of `ValidationError`, so this used to
        # escape and take the whole conversation turn down. A tool with a
        # broken schema is one broken tool, not a broken conversation. The
        # loader and the panel now both refuse such a schema (schema.py), so
        # reaching here means the tool predates that check or was written
        # straight into storage — hence the log, which names the tool.
        location = ".".join(str(part) for part in err.absolute_path) or "(root)"
        LOGGER.error(
            "Custom tool %s has an invalid parameters schema at %s: %s",
            tool.name,
            location,
            err.message,
        )
        return f"Invalid arguments: this tool's schema is invalid at {location}: {err.message}"
    except jsonschema.ValidationError as err:
        return f"Invalid arguments: {err.message}"

    action = tool.action
    try:
        if isinstance(action, TemplateAction):
            return await execute_template(hass, action, args)
        if isinstance(action, ServiceAction):
            return await execute_service(hass, action, args)
        if isinstance(action, RESTAction):
            return await execute_rest(hass, action, args)
        if isinstance(action, ScriptAction):
            return await execute_script(hass, action, args)
        if isinstance(action, MCPAction):
            return await execute_mcp(hass, action, args)
    except Exception:  # noqa: BLE001 — boundary, must not leak details to LLM
        LOGGER.exception("Custom tool %s execution failed", tool.name)
        return "Tool execution failed; check Home Assistant logs."

    return f"Unsupported action type: {type(action).__name__}"
