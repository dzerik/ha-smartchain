"""voluptuous schemas for /config/smartchain/tools.yaml."""

import voluptuous as vol

from ..const import MCP_NAME_PATTERN, TOOL_NAME_PATTERN

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
        vol.Optional("payload", default=None): vol.Any(dict, None),
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

_ACTION_TYPES = ["service", "template", "rest", "script"]


def _validate_action(value: object) -> dict:
    """Validate the action block with a clear error on unknown type."""
    if not isinstance(value, dict) or "type" not in value:
        raise vol.Invalid("action must be a dict with a 'type' key")
    action_type = value["type"]
    if action_type == "service":
        return _SERVICE_ACTION(value)
    if action_type == "template":
        return _TEMPLATE_ACTION(value)
    if action_type == "rest":
        return _REST_ACTION(value)
    if action_type == "script":
        return _SCRIPT_ACTION(value)
    raise vol.Invalid(f"unknown action type {action_type!r}; expected one of {_ACTION_TYPES}")


_ACTION = _validate_action

TOOL_SCHEMA = vol.Schema(
    {
        vol.Required("name"): _NAME,
        vol.Required("description"): _NON_EMPTY_STR,
        vol.Required("parameters"): _PARAMETERS,
        vol.Required("action"): _ACTION,
    }
)

_MCP_NAME = vol.All(str, vol.Match(MCP_NAME_PATTERN))

_MCP_SHARED = {
    vol.Required("name"): _MCP_NAME,
    vol.Optional("prefix"): vol.Any(None, str),
    vol.Optional("include_tools", default=list): [str],
    vol.Optional("exclude_tools", default=list): [str],
    vol.Optional("enabled", default=True): bool,
}

_STDIO_SERVER = vol.Schema(
    {
        **_MCP_SHARED,
        vol.Required("transport"): "stdio",
        vol.Required("command"): _NON_EMPTY_STR,
        vol.Optional("args", default=list): [str],
        vol.Optional("env", default=dict): {str: str},
    }
)

_SSE_SERVER = vol.Schema(
    {
        **_MCP_SHARED,
        vol.Required("transport"): "sse",
        vol.Required("url"): _NON_EMPTY_STR,
        vol.Optional("headers", default=dict): {str: str},
        vol.Optional("timeout", default=30): vol.All(int, vol.Range(min=1, max=300)),
        vol.Optional("verify_ssl", default=True): bool,
    }
)

_HTTP_SERVER = vol.Schema(
    {
        **_MCP_SHARED,
        vol.Required("transport"): "http",
        vol.Required("url"): _NON_EMPTY_STR,
        vol.Optional("headers", default=dict): {str: str},
        vol.Optional("timeout", default=30): vol.All(int, vol.Range(min=1, max=300)),
        vol.Optional("verify_ssl", default=True): bool,
    }
)

_MCP_TRANSPORTS = ["stdio", "sse", "http"]


def _validate_mcp_server(value: object) -> dict:
    """Discriminated dispatch on `transport` with a clear unknown-transport error."""
    if not isinstance(value, dict) or "transport" not in value:
        raise vol.Invalid("mcp_server must be a dict with a 'transport' key")
    transport = value["transport"]
    if transport == "stdio":
        return _STDIO_SERVER(value)
    if transport == "sse":
        return _SSE_SERVER(value)
    if transport == "http":
        return _HTTP_SERVER(value)
    raise vol.Invalid(f"unknown transport {transport!r}; expected one of {_MCP_TRANSPORTS}")


MCP_SERVER_SCHEMA = _validate_mcp_server

TOOLS_FILE_SCHEMA = vol.Schema(
    {
        vol.Optional("tools", default=list): [TOOL_SCHEMA],
        vol.Optional("mcp_servers", default=list): [MCP_SERVER_SCHEMA],
    }
)
