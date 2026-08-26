"""voluptuous schemas for /config/smartchain/tools.yaml."""

import jsonschema
import voluptuous as vol
from jsonschema.validators import validator_for

from ..const import (
    ENTITY_DEFAULT_PRESET,
    ENTITY_PRESETS,
    ENTITY_SOURCE_TYPE,
    MCP_NAME_PATTERN,
    MEMORY_BACKEND_TYPES,
    MEMORY_DEFAULT_LOGBOOK_POLL_MINUTES,
    MEMORY_IDENTIFIER_PATTERN,
    MEMORY_LOGBOOK_POLL_MAX_MINUTES,
    MEMORY_LOGBOOK_POLL_MIN_MINUTES,
    MEMORY_STORE_NAME_PATTERN,
    REST_DEFAULT_TIMEOUT,
    REST_MAX_TIMEOUT,
    REST_METHODS,
    REST_MIN_TIMEOUT,
    REST_RESPONSE_FORMATS,
    TOOL_ACTION_TYPES,
    TOOL_NAME_PATTERN,
    TOOL_SCRIPT_PATTERN,
)
from .model import ACTION_MAX_TIMEOUT, ACTION_MIN_TIMEOUT

_NAME = vol.All(str, vol.Match(TOOL_NAME_PATTERN))
_NON_EMPTY_STR = vol.All(str, vol.Length(min=1))
_MEMORY_IDENTIFIER = vol.All(str, vol.Match(MEMORY_IDENTIFIER_PATTERN))

# Bounded exactly like the REST executor's `timeout`, but deliberately WITHOUT
# `default=`: the default lives on the dataclass (`model.ACTION_DEFAULT_TIMEOUT`)
# and is applied by `loader.action_from_dict`. A `default=` here would make
# `validate_action` add a key the panel's own form never wrote, so opening a
# preset-installed tool and pressing Save with nothing changed would rewrite the
# stored subentry — the round trip `test_a_preset_survives_open_and_save_unchanged`
# exists to protect. Validated when present, defaulted when absent.
_ACTION_TIMEOUT = vol.All(int, vol.Range(min=ACTION_MIN_TIMEOUT, max=ACTION_MAX_TIMEOUT))


def _valid_json_schema(value: dict) -> dict:
    """Hold `parameters` to the JSON Schema metaschema, not just to its shell.

    The shell check below only says `type: object`, `properties` is a dict and
    `required` is a list of strings — nothing about what is *inside* a property.
    So `city: {type: str}` passed the file and the form and first failed inside
    `jsonschema.validate` at call time, as a `SchemaError`, in front of the
    model. USAGE §7.0.1 promises the opposite: validated before it is saved.

    `validator_for` picks the same validator `jsonschema.validate` will pick for
    this schema — honouring a `$schema` key if the user wrote one — so what
    passes here cannot fail there, and what fails here would have failed there.
    """
    try:
        validator_for(value, default=jsonschema.Draft202012Validator).check_schema(value)
    except jsonschema.SchemaError as err:
        location = ".".join(str(part) for part in err.absolute_path) or "(root)"
        raise vol.Invalid(f"invalid JSON Schema at {location}: {err.message}") from err
    return value


PARAMETERS_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("type"): "object",
            vol.Required("properties"): dict,
            vol.Optional("required"): [str],
        },
        extra=vol.ALLOW_EXTRA,
    ),
    _valid_json_schema,
)

_SERVICE_ACTION = vol.Schema(
    {
        vol.Required("type"): "service",
        vol.Required("domain"): _NON_EMPTY_STR,
        vol.Required("service"): _NON_EMPTY_STR,
        vol.Optional("target", default=dict): dict,
        vol.Optional("data", default=dict): dict,
        vol.Optional("response", default=False): bool,
        vol.Optional("timeout"): _ACTION_TIMEOUT,
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
        vol.Required("method"): vol.In(REST_METHODS),
        vol.Required("url"): _NON_EMPTY_STR,
        vol.Optional("headers", default=dict): {str: str},
        vol.Optional("payload", default=None): vol.Any(dict, None),
        vol.Optional("timeout", default=REST_DEFAULT_TIMEOUT): vol.All(
            int, vol.Range(min=REST_MIN_TIMEOUT, max=REST_MAX_TIMEOUT)
        ),
        vol.Optional("response_format", default="text"): vol.In(REST_RESPONSE_FORMATS),
    }
)

_SCRIPT_ACTION = vol.Schema(
    {
        vol.Required("type"): "script",
        vol.Required("script"): vol.All(str, vol.Match(TOOL_SCRIPT_PATTERN)),
        vol.Optional("variables", default=dict): dict,
        vol.Optional("timeout"): _ACTION_TIMEOUT,
    }
)

# The lists the form's pickers offer come from const.py, so a tool built in the
# UI cannot offer an action type, an HTTP method or a response format this
# validator would then reject.
_ACTION_TYPES = TOOL_ACTION_TYPES


def validate_action(value: object) -> dict:
    """Validate the action block with a clear error on unknown type.

    Public because the `tool` subentry path validates the action dict it
    composes from the form with exactly this function — the point being that a
    tool written in YAML and one built in the panel go through one validator,
    not two that can drift.
    """
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


_ACTION = validate_action

TOOL_SCHEMA = vol.Schema(
    {
        vol.Required("name"): _NAME,
        vol.Required("description"): _NON_EMPTY_STR,
        vol.Required("parameters"): PARAMETERS_SCHEMA,
        vol.Required("action"): _ACTION,
        vol.Optional("enabled", default=True): bool,
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


# A domain (`sensor`) or a full entity_id (`sensor.kitchen_temperature`).
_ENTITY_SELECTOR = vol.Match(r"^[a-z_]+(\.[a-z0-9_]+)?\Z")

_SOURCE_SCHEMA = vol.Schema(
    {
        vol.Required("type"): vol.In([ENTITY_SOURCE_TYPE]),
        vol.Optional("preset", default=ENTITY_DEFAULT_PRESET): vol.In(ENTITY_PRESETS),
        vol.Optional("index_states", default=False): bool,
        vol.Optional("include", default=list): [_ENTITY_SELECTOR],
        vol.Optional("exclude", default=list): [_ENTITY_SELECTOR],
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
        vol.Optional("source"): _SOURCE_SCHEMA,
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

    # Must run against the RAW mapping, before _STORE_SCHEMA applies its
    # defaults: `ingest_conversation` defaults to True, so a check performed
    # after validation could not tell a user's explicit `true` from the
    # default and would reject every entity store anyone ever wrote.
    raw_stores = value.get("stores")
    if isinstance(raw_stores, list):
        for raw in raw_stores:
            if not isinstance(raw, dict):
                continue
            source = raw.get("source")
            if not isinstance(source, dict) or source.get("type") != ENTITY_SOURCE_TYPE:
                continue
            clashing = sorted(
                {"retention_days", "ingest_conversation", "ingest_logbook"} & set(raw)
            )
            if clashing:
                raise vol.Invalid(
                    f"memory store {raw.get('name')!r} declares source.type: "
                    f"{ENTITY_SOURCE_TYPE}, so these keys do not apply and were "
                    f"rejected: {clashing}. Retention would delete indexed entities "
                    "by age, and conversation or logbook ingest would write "
                    "non-entity documents into the index."
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
