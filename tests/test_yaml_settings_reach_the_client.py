"""User settings must survive the whole trip from tools.yaml to the client.

Every setting here was already tested from its dataclass downwards — `SSEConfig
-> sse_client`, `QdrantBackend.__init__ -> _request`. Nothing tested the half
above: whether the key the user actually writes in `tools.yaml` ever reaches
that dataclass. Four separate mutations that threw the user's value away and
hard-coded a default survived the entire suite:

  - `loader.py` SSE branch, `verify_ssl=d.get("verify_ssl", True)` -> `True`
  - `loader.py` HTTP branch, the same
  - `loader.py` qdrant `BackendConfig`, the same
  - `backends/__init__.py`, `verify_ssl=bool(getattr(config, ...))` -> `True`

`verify_ssl` decides whether TLS certificates are checked on the connection
that carries a bearer token, an `api-key` header and every remembered
conversation turn. Both directions therefore matter, and each test below
asserts both: `false` in the file must arrive as False (or the option is a
placebo for the self-signed deployments it exists for), and an absent key must
arrive as True (or a mutation would make "no certificate checking" the silent
default for users who never asked for it).

The tests start from YAML *text*, not from a validated dict, so the schema
default and the loader's `.get()` fallback are both inside the covered path.

`verify_ssl` turned out not to be alone: the same substitute-a-default mutation
was run over every neighbouring key the loader reads, and the ones that also
survived are covered further down — the MCP `headers`, `env`, `include_tools`,
`exclude_tools`, `prefix`, `args` and `timeout`, and the memory backend's
`url`, `api_key`, `collection`, `dsn`, `table` and `path`.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.smartchain.tools.loader import load_tools_file
from custom_components.smartchain.tools.mcp.config import HTTPConfig, SSEConfig, StdioConfig
from custom_components.smartchain.tools.memory.backends import create_backend
from custom_components.smartchain.tools.memory.backends.pgvector import PgVectorBackend
from custom_components.smartchain.tools.memory.backends.qdrant import QdrantBackend
from custom_components.smartchain.tools.memory.backends.sqlite_numpy import SqliteNumpyBackend

# --- MCP SSE / HTTP transports ---------------------------------------------


def _mcp_yaml(transport: str, verify_ssl_line: str) -> str:
    return (
        "tools: []\n"
        "mcp_servers:\n"
        "  - name: remote\n"
        f"    transport: {transport}\n"
        "    url: https://selfsigned.example/mcp\n"
        "    headers:\n"
        '      Authorization: "Bearer s3cret"\n'
        f"{verify_ssl_line}"
    )


@pytest.mark.parametrize(
    ("transport", "expected_cls"),
    [("sse", SSEConfig), ("http", HTTPConfig)],
)
def test_verify_ssl_false_in_yaml_reaches_the_mcp_transport_config(
    tmp_path: Path, transport: str, expected_cls: type
) -> None:
    """`verify_ssl: false` written by the user arrives as False on the dataclass."""
    target = tmp_path / "tools.yaml"
    target.write_text(_mcp_yaml(transport, "    verify_ssl: false\n"))

    (server,) = load_tools_file(target).mcp_servers

    assert isinstance(server, expected_cls)
    assert server.verify_ssl is False


@pytest.mark.parametrize(
    ("transport", "expected_cls"),
    [("sse", SSEConfig), ("http", HTTPConfig)],
)
def test_omitting_verify_ssl_in_yaml_keeps_the_mcp_transport_checking_certs(
    tmp_path: Path, transport: str, expected_cls: type
) -> None:
    """No key in the file means certificates stay checked.

    The direction that matters most: a mutation hard-coding False here would
    silently drop TLS verification for every user who never asked for it.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(_mcp_yaml(transport, ""))

    (server,) = load_tools_file(target).mcp_servers

    assert isinstance(server, expected_cls)
    assert server.verify_ssl is True


@pytest.mark.parametrize("transport", ["sse", "http"])
def test_verify_ssl_true_in_yaml_is_carried_not_guessed(tmp_path: Path, transport: str) -> None:
    """An explicit `true` also arrives as True — the value is read, not invented."""
    target = tmp_path / "tools.yaml"
    target.write_text(_mcp_yaml(transport, "    verify_ssl: true\n"))

    (server,) = load_tools_file(target).mcp_servers

    assert server.verify_ssl is True


# --- Qdrant memory backend --------------------------------------------------


def _qdrant_yaml(verify_ssl_line: str) -> str:
    return (
        "tools: []\n"
        "memory:\n"
        "  stores:\n"
        "    - name: conversations\n"
        "      embeddings: Ollama Embeddings\n"
        "      backend:\n"
        "        type: qdrant\n"
        "        url: https://selfsigned.example:6333\n"
        "        api_key: qdrant-secret\n"
        "        collection: house_notes\n"
        f"{verify_ssl_line}"
    )


def test_verify_ssl_false_in_yaml_reaches_the_backend_config(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text(_qdrant_yaml("        verify_ssl: false\n"))

    (store,) = load_tools_file(target).memory_settings.stores

    assert store.backend.type == "qdrant"
    assert store.backend.verify_ssl is False


def test_omitting_verify_ssl_in_yaml_keeps_the_backend_checking_certs(
    tmp_path: Path,
) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text(_qdrant_yaml(""))

    (store,) = load_tools_file(target).memory_settings.stores

    assert store.backend.verify_ssl is True


@pytest.mark.parametrize(("written", "expected"), [("false", False), ("true", True)])
def test_yaml_verify_ssl_reaches_the_constructed_qdrant_backend(
    tmp_path: Path, written: str, expected: bool
) -> None:
    """The last link: loader -> BackendConfig -> create_backend -> QdrantBackend.

    `create_backend` reads the flag off the config with a `getattr` default of
    its own, so it can drop the user's value independently of the loader. This
    walks the whole chain from the file the user edits to the object that calls
    `async_get_clientsession`.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(_qdrant_yaml(f"        verify_ssl: {written}\n"))

    (store,) = load_tools_file(target).memory_settings.stores
    backend = create_backend(MagicMock(), store.backend, store.name, tmp_path)

    assert isinstance(backend, QdrantBackend)
    assert backend.verify_ssl is expected


def test_qdrant_backend_from_yaml_without_the_key_checks_certs(tmp_path: Path) -> None:
    """Same chain, key absent — the constructed backend must still verify."""
    target = tmp_path / "tools.yaml"
    target.write_text(_qdrant_yaml(""))

    (store,) = load_tools_file(target).memory_settings.stores
    backend = create_backend(MagicMock(), store.backend, store.name, tmp_path)

    assert backend.verify_ssl is True


# --- the fallbacks under the schema default ---------------------------------
#
# Above this line every "key absent" case is decided by the *schema*, which
# fills `verify_ssl: true` before the loader ever looks. That makes the
# loader's own `.get(..., True)` and the factory's `getattr(..., True)` dead
# code today — flipping either to False leaves the YAML tests green, which was
# verified by running exactly that mutation. They are still the value that
# applies the day a key stops being schema-defaulted (a new caller, a relaxed
# `extra=ALLOW_EXTRA` path, a hand-built dict), so each is pinned directly.


def test_loader_defaults_verify_ssl_on_when_the_dict_has_no_key() -> None:
    """The loader does not rely on the schema having filled the key in."""
    from custom_components.smartchain.tools.loader import _server_from_dict

    for transport in ("sse", "http"):
        cfg = _server_from_dict({"name": "remote", "transport": transport, "url": "https://x/mcp"})
        assert cfg.verify_ssl is True, transport


def test_memory_loader_defaults_verify_ssl_on_when_the_backend_dict_has_no_key() -> None:
    from custom_components.smartchain.tools.loader import _memory_from_validated

    settings = _memory_from_validated(
        {
            "memory": {
                "stores": [
                    {
                        "name": "conversations",
                        "embeddings": "E",
                        "backend": {"type": "qdrant", "url": "https://x:6333"},
                    }
                ]
            }
        }
    )

    (store,) = settings.stores
    assert store.backend.verify_ssl is True


def test_create_backend_defaults_verify_ssl_on_for_a_config_without_the_field(
    tmp_path: Path,
) -> None:
    """A config object that has no `verify_ssl` at all must not disable checking."""

    class _MinimalConfig:
        type = "qdrant"
        url = "https://x:6333"
        collection = "mem"
        api_key = None

    backend = create_backend(MagicMock(), _MinimalConfig(), "conversations", tmp_path)

    assert backend.verify_ssl is True


# --- the neighbouring MCP keys ----------------------------------------------
#
# Each of these was verified to be uncovered the same way: substitute the
# user's value with the hard-coded default in `_server_from_dict` and the whole
# MCP + loader suite (88 tests) stayed green.


def test_yaml_headers_reach_the_remote_transport_config(tmp_path: Path) -> None:
    """The bearer token the user wrote is the one the transport will send.

    `test_mcp_verify_ssl` proves `SSEConfig.headers` reaches `sse_client`;
    nothing proved the file's `headers:` block reaches `SSEConfig`. Dropping
    them makes every authenticated MCP server fail to connect, and rewriting
    them would send the user's token somewhere they did not write.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools: []\n"
        "mcp_servers:\n"
        "  - name: sse_one\n"
        "    transport: sse\n"
        "    url: https://a.example/mcp\n"
        "    headers:\n"
        '      Authorization: "Bearer sse-token"\n'
        "      X-Tenant: acme\n"
        "  - name: http_one\n"
        "    transport: http\n"
        "    url: https://b.example/mcp\n"
        "    headers:\n"
        '      Authorization: "Bearer http-token"\n'
    )

    sse, http = load_tools_file(target).mcp_servers

    assert isinstance(sse, SSEConfig)
    assert sse.headers == {"Authorization": "Bearer sse-token", "X-Tenant": "acme"}
    assert isinstance(http, HTTPConfig)
    assert http.headers == {"Authorization": "Bearer http-token"}


def test_yaml_env_and_args_reach_the_stdio_server_config(tmp_path: Path) -> None:
    """`env:` is how a stdio MCP server is given its credentials.

    Losing it starts the subprocess unauthenticated; rewriting it would hand
    the secret to a different process than the user described.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools: []\n"
        "mcp_servers:\n"
        "  - name: fs\n"
        "    transport: stdio\n"
        "    command: npx\n"
        '    args: ["-y", "server-filesystem", "/config/notes"]\n'
        "    env:\n"
        "      API_TOKEN: env-secret\n"
    )

    (server,) = load_tools_file(target).mcp_servers

    assert isinstance(server, StdioConfig)
    assert server.command == "npx"
    assert server.args == ["-y", "server-filesystem", "/config/notes"]
    assert server.env == {"API_TOKEN": "env-secret"}


def test_yaml_tool_filters_and_prefix_reach_the_server_config(tmp_path: Path) -> None:
    """`include_tools`/`exclude_tools` decide what the model may call.

    They are an allowlist and a denylist over a remote server's tools, so a
    loader that dropped them would expose every tool the server offers —
    including the `delete_*` one the user listed under `exclude_tools`.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools: []\n"
        "mcp_servers:\n"
        "  - name: fs\n"
        "    transport: stdio\n"
        "    command: npx\n"
        "    prefix: files\n"
        "    include_tools: [read_file, list_dir]\n"
        "    exclude_tools: [delete_file]\n"
    )

    (server,) = load_tools_file(target).mcp_servers

    assert server.prefix == "files"
    assert server.include_tools == ["read_file", "list_dir"]
    assert server.exclude_tools == ["delete_file"]


def test_yaml_timeout_and_enabled_reach_the_server_config(tmp_path: Path) -> None:
    """A disabled server must stay disabled, and a raised timeout must apply."""
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools: []\n"
        "mcp_servers:\n"
        "  - name: slow\n"
        "    transport: sse\n"
        "    url: https://a.example/mcp\n"
        "    timeout: 120\n"
        "    enabled: false\n"
    )

    (server,) = load_tools_file(target).mcp_servers

    assert server.timeout == 120
    assert server.enabled is False


# --- the neighbouring memory-backend keys -----------------------------------
#
# Same probe, same result: substituting the default for the user's value in
# `_memory_from_validated` and in `create_backend` left the memory suite green
# for `url`, `api_key`, `collection`, `dsn`, `table` and `path`.


def test_yaml_qdrant_address_and_credential_reach_the_backend(tmp_path: Path) -> None:
    """Where the memories go, and what authenticates the request.

    `url` is the host every remembered conversation turn is shipped to and
    `api_key` becomes the `api-key` header on each request — the two values
    that decide who ends up holding the data.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(_qdrant_yaml(""))

    (store,) = load_tools_file(target).memory_settings.stores
    assert store.backend.url == "https://selfsigned.example:6333"
    assert store.backend.api_key == "qdrant-secret"
    assert store.backend.collection == "house_notes"

    backend = create_backend(MagicMock(), store.backend, store.name, tmp_path)
    assert isinstance(backend, QdrantBackend)
    assert backend.url == "https://selfsigned.example:6333"
    # Deliberately not `smartchain_memory`: that is the factory's own default,
    # so a fixture using it would let "ignore the user's collection" pass.
    assert backend.collection == "house_notes"
    assert backend._headers["api-key"] == "qdrant-secret"


def test_yaml_pgvector_dsn_and_table_reach_the_backend(tmp_path: Path) -> None:
    """The DSN carries the database password; the table names the data."""
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools: []\n"
        "memory:\n"
        "  stores:\n"
        "    - name: conversations\n"
        "      embeddings: Ollama Embeddings\n"
        "      backend:\n"
        "        type: pgvector\n"
        "        dsn: postgresql://u:p@db.example/ha\n"
        "        table: smartchain_conversations\n"
    )

    (store,) = load_tools_file(target).memory_settings.stores
    assert store.backend.dsn == "postgresql://u:p@db.example/ha"

    backend = create_backend(MagicMock(), store.backend, store.name, tmp_path)
    assert isinstance(backend, PgVectorBackend)
    # No public accessor for the DSN — it is deliberately private — but the
    # point of the test is that the user's value, not a default, is what the
    # backend will connect with.
    assert backend._dsn == "postgresql://u:p@db.example/ha"
    assert backend.table == "smartchain_conversations"


def test_yaml_backend_path_decides_where_the_database_file_lands(
    tmp_path: Path,
) -> None:
    """A configured `path:` must be used, and an absent one must not be invented.

    The file holds every remembered conversation turn in plaintext, so a loader
    that ignored `path:` would write it somewhere the user did not choose —
    possibly outside the directory they back up or encrypt.
    """
    chosen = tmp_path / "elsewhere" / "memories.db"
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools: []\n"
        "memory:\n"
        "  stores:\n"
        "    - name: conversations\n"
        "      embeddings: Ollama Embeddings\n"
        "      backend:\n"
        "        type: sqlite_numpy\n"
        f"        path: {chosen}\n"
    )

    (store,) = load_tools_file(target).memory_settings.stores
    assert store.backend.path == str(chosen)

    backend = create_backend(MagicMock(), store.backend, store.name, tmp_path)
    assert isinstance(backend, SqliteNumpyBackend)
    assert backend.db_path == chosen


def test_backend_without_a_path_falls_back_to_the_store_name(tmp_path: Path) -> None:
    """No `path:` means the storage dir and the store's own name — nothing else."""
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools: []\n"
        "memory:\n"
        "  stores:\n"
        "    - name: conversations\n"
        "      embeddings: Ollama Embeddings\n"
    )

    (store,) = load_tools_file(target).memory_settings.stores
    assert store.backend.path is None

    backend = create_backend(MagicMock(), store.backend, store.name, tmp_path / "storage")
    assert backend.db_path == tmp_path / "storage" / "conversations.db"


def test_yaml_logbook_poll_interval_reaches_the_store_config(tmp_path: Path) -> None:
    """How often the home's activity log is read and embedded.

    Ignoring the user's value would poll — and ingest — far more of the home's
    activity than they asked for.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools: []\n"
        "memory:\n"
        "  stores:\n"
        "    - name: conversations\n"
        "      embeddings: Ollama Embeddings\n"
        "      ingest_logbook:\n"
        "        enabled: true\n"
        "        poll_interval_minutes: 720\n"
    )

    (store,) = load_tools_file(target).memory_settings.stores

    assert store.logbook.enabled is True
    assert store.logbook.poll_interval_minutes == 720


# --- the tool actions the user writes ---------------------------------------
#
# The same probe over `action_from_dict` found eight more survivors: `data`,
# `response`, `headers`, `payload`, `timeout`, `response_format`, `variables`
# and the tool's own `parameters`. `action_from_dict` is shared with the panel's
# tool subentry, so these cover both authoring routes at once.


def test_yaml_rest_action_headers_and_body_reach_the_action(tmp_path: Path) -> None:
    """A REST tool's `headers:` is where the user's third-party API key lives.

    Dropping it makes the call unauthenticated; substituting it would send a
    different credential than the one written in the file.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: fetch_price\n"
        "    description: Fetch a price\n"
        "    parameters:\n"
        "      type: object\n"
        "      properties:\n"
        "        symbol: { type: string }\n"
        "      required: [symbol]\n"
        "    action:\n"
        "      type: rest\n"
        "      method: POST\n"
        "      url: https://api.example/quote\n"
        "      headers:\n"
        '        Authorization: "Bearer rest-token"\n'
        "      payload:\n"
        '        symbol: "{{ symbol }}"\n'
        "      timeout: 45\n"
        "      response_format: json\n"
    )

    (tool,) = load_tools_file(target).yaml_tools

    assert tool.action.headers == {"Authorization": "Bearer rest-token"}
    assert tool.action.payload == {"symbol": "{{ symbol }}"}
    assert tool.action.timeout == 45
    assert tool.action.response_format == "json"
    # The declared argument schema is what the model is shown; an emptied one
    # leaves it guessing at the arguments.
    assert tool.parameters["properties"] == {"symbol": {"type": "string"}}
    assert tool.parameters["required"] == ["symbol"]


@pytest.mark.parametrize("written", ["true", "false"])
def test_yaml_service_action_data_and_response_flag_reach_the_action(
    tmp_path: Path, written: str
) -> None:
    """`response: true` returns the service's reply to the model.

    That decides whether a service's output — a calendar, a shopping list, a
    to-do query — is handed to the LLM at all, so a hard-coded value in either
    direction is a data-exposure change, not a cosmetic one.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: list_events\n"
        "    description: List events\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action:\n"
        "      type: service\n"
        "      domain: calendar\n"
        "      service: get_events\n"
        "      target:\n"
        "        entity_id: calendar.family\n"
        "      data:\n"
        "        duration: { hours: 24 }\n"
        f"      response: {written}\n"
    )

    (tool,) = load_tools_file(target).yaml_tools

    assert tool.action.target == {"entity_id": "calendar.family"}
    assert tool.action.data == {"duration": {"hours": 24}}
    assert tool.action.response is (written == "true")


def test_yaml_script_action_variables_reach_the_action(tmp_path: Path) -> None:
    """The variables are what the script actually runs with."""
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: run_scene\n"
        "    description: Run a scene\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action:\n"
        "      type: script\n"
        "      script: script.evening\n"
        "      variables:\n"
        "        brightness: 40\n"
    )

    (tool,) = load_tools_file(target).yaml_tools

    assert tool.action.script == "script.evening"
    assert tool.action.variables == {"brightness": 40}
