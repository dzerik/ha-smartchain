"""voluptuous schemas for /config/smartchain/tools.yaml."""

import voluptuous as vol

from ..const import TOOL_NAME_PATTERN

_NAME = vol.All(str, vol.Match(TOOL_NAME_PATTERN))
_NON_EMPTY_STR = vol.All(str, vol.Length(min=1))

_PARAMETERS = vol.Schema(
    {
        vol.Required("type"): "object",
        vol.Required("properties"): dict,
        vol.Optional("required"): [str],
    },
    extra=vol.ALLOW_EXTRA,
)

_SERVICE_ACTION = vol.Schema(
    {
        vol.Required("type"): "service",
        vol.Required("domain"): _NON_EMPTY_STR,
        vol.Required("service"): _NON_EMPTY_STR,
        vol.Optional("target", default=dict): dict,
        vol.Optional("data", default=dict): dict,
        vol.Optional("response", default=False): bool,
    }
)

_TEMPLATE_ACTION = vol.Schema(
    {
        vol.Required("type"): "template",
        vol.Required("value_template"): _NON_EMPTY_STR,
    }
)

_REST_ACTION = vol.Schema(
    {
        vol.Required("type"): "rest",
        vol.Required("method"): vol.In(["GET", "POST", "PUT", "DELETE"]),
        vol.Required("url"): _NON_EMPTY_STR,
        vol.Optional("headers", default=dict): {str: str},
        vol.Optional("payload"): vol.Any(dict, None),
        vol.Optional("timeout", default=10): vol.All(int, vol.Range(min=1, max=120)),
        vol.Optional("response_format", default="text"): vol.In(["text", "json"]),
    }
)

_SCRIPT_ACTION = vol.Schema(
    {
        vol.Required("type"): "script",
        vol.Required("script"): vol.All(str, vol.Match(r"^script\.[a-z_][a-z0-9_]*$")),
        vol.Optional("variables", default=dict): dict,
    }
)

_ACTION = vol.Any(_SERVICE_ACTION, _TEMPLATE_ACTION, _REST_ACTION, _SCRIPT_ACTION)

TOOL_SCHEMA = vol.Schema(
    {
        vol.Required("name"): _NAME,
        vol.Required("description"): _NON_EMPTY_STR,
        vol.Required("parameters"): _PARAMETERS,
        vol.Required("action"): _ACTION,
    }
)

TOOLS_FILE_SCHEMA = vol.Schema(
    {
        vol.Required("tools"): [TOOL_SCHEMA],
    }
)
