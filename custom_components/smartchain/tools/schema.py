"""voluptuous schemas for /config/smartchain/tools.yaml."""

import voluptuous as vol

from ..const import (
    MCP_NAME_PATTERN,
    MEMORY_BACKEND_TYPES,
    MEMORY_DEFAULT_LOGBOOK_POLL_MINUTES,
    MEMORY_IDENTIFIER_PATTERN,
    MEMORY_LOGBOOK_POLL_MAX_MINUTES,
    MEMORY_LOGBOOK_POLL_MIN_MINUTES,
    MEMORY_STORE_NAME_PATTERN,
    TOOL_NAME_PATTERN,
)

_NAME = vol.All(str, vol.Match(TOOL_NAME_PATTERN))
_NON_EMPTY_STR = vol.All(str, vol.Length(min=1))
_MEMORY_IDENTIFIER = vol.All(str, vol.Match(MEMORY_IDENTIFIER_PATTERN))

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
    vol.Optional("prefix"): vol.Any(None, vol.All(str, vol.Any("", vol.Match(TOOL_NAME_PATTERN)))),
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

_LOGBOOK_SCHEMA = vol.Schema(
    {
        vol.Optional("enabled", default=False): bool,
        vol.Optional("domains", default=list): [str],
        vol.Optional("poll_interval_minutes", default=MEMORY_DEFAULT_LOGBOOK_POLL_MINUTES): vol.All(
            int,
            vol.Range(
                min=MEMORY_LOGBOOK_POLL_MIN_MINUTES,
                max=MEMORY_LOGBOOK_POLL_MAX_MINUTES,
            ),
        ),
    }
)


_BACKEND_SCHEMA = vol.Schema(
    {
        vol.Optional("type", default="sqlite_numpy"): vol.In(MEMORY_BACKEND_TYPES),
        vol.Optional("path"): vol.Any(None, str),
        vol.Optional("dsn"): vol.Any(None, str),
        # `table` lands in pgvector DDL/DML and `collection` in a qdrant URL
        # path, neither of which can be parameterised — so both are restricted
        # to a plain identifier rather than accepted as free-form strings.
        vol.Optional("table"): vol.Any(None, _MEMORY_IDENTIFIER),
        vol.Optional("url"): vol.Any(None, str),
        vol.Optional("api_key"): vol.Any(None, str),
        vol.Optional("collection"): vol.Any(None, _MEMORY_IDENTIFIER),
        vol.Optional("verify_ssl", default=True): bool,
    }
)


_STORE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): vol.All(str, vol.Match(MEMORY_STORE_NAME_PATTERN)),
        vol.Required("embeddings"): _NON_EMPTY_STR,
        vol.Optional("description", default=""): str,
        vol.Optional("backend", default=dict): _BACKEND_SCHEMA,
        vol.Optional("retention_days", default=90): vol.All(int, vol.Range(min=0, max=3650)),
        vol.Optional("ingest_conversation", default=True): bool,
        vol.Optional("ingest_logbook", default=dict): _LOGBOOK_SCHEMA,
    }
)


def _validate_memory(value: object) -> dict:
    """Validate the memory block and reject the pre-5.0.0 flat shape.

    Credentials no longer live in YAML, so a block carrying `provider` or
    `api_key` cannot be migrated automatically — there is no subentry to point
    at until the user creates one. Fail loudly with the exact steps.
    """
    if not isinstance(value, dict):
        raise vol.Invalid("memory must be a mapping")

    legacy_keys = {"provider", "model", "api_key", "base_url"} & set(value)
    if legacy_keys:
        raise vol.Invalid(
            "the flat memory: block was replaced in v5.0.0. Create an embeddings "
            "subentry on the provider's config entry, then rewrite the block as a "
            "stores: list referencing it by name, then call smartchain.reload_tools. "
            f"Offending keys: {sorted(legacy_keys)}"
        )

    validated = vol.Schema({vol.Optional("stores", default=list): [_STORE_SCHEMA]})(value)

    seen: set[str] = set()
    for store in validated["stores"]:
        if store["name"] in seen:
            raise vol.Invalid(f"duplicate store name {store['name']!r}")
        seen.add(store["name"])
    return validated


MEMORY_SCHEMA = _validate_memory

TOOLS_FILE_SCHEMA = vol.Schema(
    {
        vol.Optional("tools", default=list): [TOOL_SCHEMA],
        vol.Optional("mcp_servers", default=list): [MCP_SERVER_SCHEMA],
        vol.Optional("memory"): MEMORY_SCHEMA,
    }
)
