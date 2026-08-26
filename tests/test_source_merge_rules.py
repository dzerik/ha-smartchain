"""What happens where tools.yaml and the config subentries meet.

Four rules live at that seam, and each one exists because breaking it is
silent — the failure shows up as a tool that works when it should not, or
config that vanished without anyone saying so.

1. **A disabled subentry still shadows its tools.yaml twin.** Turning a tool
   off must not un-shadow the file's definition of the same name and start it
   running. Note that this is the *opposite* of the within-source rule, where a
   disabled entry must not reserve its name; `subentry_tool_names` says why
   both are right.
2. **A tools.yaml failure is confined to tools.yaml.** Everything built in the
   panel still loads, the file keeps whatever it last successfully said, and
   the error is reported rather than swallowed.
3. **`tool/schema` never blanks the client's own draft.** Stored credentials
   are withheld; a value the client just typed comes home.
4. **A tool subentry outlives the MCP rebuild.** Stopping the MCP manager
   deregisters by name, so it must happen before the merged registry is
   installed, not after — and a name a live MCP server already provides is
   refused in the form.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_EMBEDDINGS,
    SUBENTRY_TYPE_MEMORY_STORE,
    SUBENTRY_TYPE_TOOL,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

HEADER_SECRET = "Bearer typed-just-now"


@pytest.fixture
def tools_dir(hass: HomeAssistant, tmp_path_factory) -> Path:
    """A writable config dir, set before setup runs its first tools.yaml load."""
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    hass.config.config_dir = str(cdir)
    return cdir / "smartchain"


def _tool_subentry(title: str, data: dict) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=data, subentry_type=SUBENTRY_TYPE_TOOL, title=title, unique_id=None
    )


def _template_tool(description: str = "x", *, enabled: bool = True) -> dict:
    return {
        "description": description,
        "parameters": {"type": "object", "properties": {}},
        "action": {"type": "template", "value_template": "{{ 'ok' }}"},
        "enabled": enabled,
        "params_mode": "simple",
    }


async def _entry(hass: HomeAssistant, subentries=()) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sk-provider-secret"},
        subentries_data=list(subentries),
        minor_version=2,
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return entry


# --- 1. a disabled subentry still shadows its twin -------------------------


DANGEROUS_YAML = """
tools:
  - name: danger_tool
    description: Unlock the front door
    parameters:
      type: object
      properties: {}
    action:
      type: service
      domain: lock
      service: unlock
      target:
        entity_id: lock.front
"""


async def test_disabling_a_tool_does_not_start_its_tools_yaml_twin(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The switch says off, so nothing of that name may run.

    The Import button manufactures these twins by design — it copies tools.yaml
    into subentries and leaves the file alone — so a user who imports, then
    switches one off, used to get the file's version back instead of nothing.
    With a `lock.unlock` in the file that is the difference between a disabled
    tool and an unlocked front door.
    """
    (tools_dir / "tools.yaml").write_text(DANGEROUS_YAML)
    await _entry(hass, [_tool_subentry("danger_tool", _template_tool(enabled=False))])

    assert hass.data[DOMAIN]["tools"].get("danger_tool") is None

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tool/list"})
    msg = await client.receive_json()
    assert msg["success"], msg

    # One row, showing the truth: the tool exists, it is off, and the file's
    # definition of the same name is being ignored rather than quietly used.
    rows = [row for row in msg["result"]["tools"] if row["name"] == "danger_tool"]
    assert [row["enabled"] for row in rows] == [False]
    assert "danger_tool" in msg["result"]["shadowed_yaml"]


async def test_an_enabled_subentry_still_shadows_the_file(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The ordinary case, unchanged by the shadowing fix."""
    (tools_dir / "tools.yaml").write_text(DANGEROUS_YAML)
    await _entry(hass, [_tool_subentry("danger_tool", _template_tool("from the form"))])

    tool = hass.data[DOMAIN]["tools"].get("danger_tool")
    assert tool is not None
    assert tool.description == "from the form"
    assert hass.data[DOMAIN]["tool_sources"]["danger_tool"] == "subentry"


def test_the_within_source_rule_is_the_opposite_and_stays_that_way() -> None:
    """Across sources a disabled entry reserves its name; within one it must not.

    Guarding both halves in one test, because the failure mode is somebody
    reading one rule, calling the other a bug, and making them match. Switching
    a tool off and adding its replacement under the same name has to keep the
    replacement.
    """
    from homeassistant.config_entries import ConfigSubentry

    from custom_components.smartchain.tools.subentry_source import (
        subentry_tool_names,
        tools_from_subentries,
    )

    def _sub(title: str, data: dict) -> ConfigSubentry:
        return ConfigSubentry(
            data=data, subentry_type=SUBENTRY_TYPE_TOOL, title=title, unique_id=None
        )

    entry = MagicMock()
    entry.subentries = {
        "a": _sub("weather", _template_tool("old", enabled=False)),
        "b": _sub("weather", _template_tool("replacement")),
    }
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = [entry]

    # Within the source: the disabled one did not reserve `weather`.
    assert [tool.description for tool in tools_from_subentries(hass)] == ["replacement"]
    # Across sources: the name is claimed regardless.
    assert subentry_tool_names(hass) == {"weather"}


# --- 2. a broken tools.yaml is confined to tools.yaml ----------------------


@pytest.fixture
def patched_store():
    """No real backend and no real embeddings provider, so a rebuild does not
    try to reach a database."""

    def _factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.unavailable_reason = None
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        return st

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry.create_embeddings_from_subentry",
            return_value=MagicMock(),
        ),
    ):
        yield


def _memory_subentries() -> list[ConfigSubentryData]:
    return [
        ConfigSubentryData(
            data={"model": "text-embedding-3-small"},
            subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
            title="emb",
            unique_id=None,
        ),
        ConfigSubentryData(
            data={
                "embeddings": "emb",
                "description": "Dialogue history",
                "backend_type": "sqlite_numpy",
                "source_type": "none",
                "retention_days": 90,
                "ingest_conversation": True,
            },
            subentry_type=SUBENTRY_TYPE_MEMORY_STORE,
            title="conversations",
            unique_id=None,
        ),
    ]


async def test_a_broken_file_at_startup_still_loads_every_subentry(
    hass: HomeAssistant, tools_dir: Path, patched_store
):
    """A mis-indented line used to cost the whole subsystem.

    `load_tools_file` raised before either merge ran, so an installation whose
    tools and stores were all built in the panel came up with an empty registry
    and no memory at all — because of a file none of it was written in.
    """
    del patched_store
    (tools_dir / "tools.yaml").write_text("tools:\n  - name: x\n   description: bad indent\n")
    await _entry(hass, [*_memory_subentries(), _tool_subentry("hello", _template_tool())])

    assert hass.data[DOMAIN]["tools"].get("hello") is not None
    assert "conversations" in hass.data[DOMAIN]["memory"].names()


async def test_the_broken_file_is_reported_not_swallowed(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Isolating the failure must not hide it.

    The error still reaches every channel it used to — the reload service
    raises — and it now also stands on the Tools tab, because a toast is tied
    to whichever action triggered the rebuild and can be missed entirely.
    """
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.smartchain.const import SERVICE_RELOAD_TOOLS

    (tools_dir / "tools.yaml").write_text("tools:\n  - name: x\n   description: bad indent\n")
    await _entry(hass, [_tool_subentry("hello", _template_tool())])

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tool/list"})
    msg = await client.receive_json()
    assert msg["result"]["yaml_error"]

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, SERVICE_RELOAD_TOOLS, {}, blocking=True)


async def test_a_file_that_breaks_later_keeps_what_it_last_said(
    hass: HomeAssistant, tools_dir: Path
):
    """A typo must not delete the YAML tools that were working a second ago.

    "Broken" means the file no longer says anything, not that it says nothing,
    so the rebuild runs against the last result the file produced — while the
    subentry tools rebuild from scratch as always.
    """
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: pong }\n"
    )
    await _entry(hass, [_tool_subentry("hello", _template_tool())])
    assert hass.data[DOMAIN]["tools"].get("ping") is not None

    (tools_dir / "tools.yaml").write_text("tools: [{ name: Bad-Name, description: x }]")
    from custom_components.smartchain import _reload_registry
    from custom_components.smartchain.tools.loader import LoaderError

    with pytest.raises(LoaderError):
        await _reload_registry(hass)

    assert hass.data[DOMAIN]["tools"].get("ping") is not None
    assert hass.data[DOMAIN]["tools"].get("hello") is not None
    assert hass.data[DOMAIN]["yaml_error"]

    # And it clears itself once the file loads again.
    (tools_dir / "tools.yaml").write_text("tools: []\n")
    await _reload_registry(hass)
    assert hass.data[DOMAIN]["yaml_error"] is None
    assert hass.data[DOMAIN]["tools"].get("ping") is None


# --- 3. the schema round trip keeps the client's own draft -----------------


async def test_a_header_typed_into_the_form_comes_back(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Redaction applies to storage, not to what the client just sent.

    `tool/schema` redacted the whole merged dict, so a header typed before a
    reshaping round trip came home blank: on a new tool there was nothing
    stored to restore it from and it saved empty, and on an edit it silently
    reverted to the old value. `ws_store_schema` had the rule right —
    `name not in secrets or name in draft` — and this is the same rule for the
    one field that holds a map.
    """
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/schema",
            "entry_id": entry.entry_id,
            "data": {"action_type": "rest", "headers": {"Authorization": HEADER_SECRET}},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["data"]["headers"] == {"Authorization": HEADER_SECRET}


async def test_the_stored_header_is_still_withheld(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The other half of the same rule, so the fix cannot become a leak.

    Nothing the client did not send comes back — not in `data`, and not in the
    serialised schema either, where the values travel as suggested values.
    """
    stored_secret = "Bearer must-not-come-back"
    entry = await _entry(
        hass,
        [
            _tool_subentry(
                "fetch",
                {
                    "description": "x",
                    "parameters": {"type": "object", "properties": {}},
                    "action": {
                        "type": "rest",
                        "method": "GET",
                        "url": "https://example.invalid/x",
                        "headers": {"Authorization": stored_secret},
                        "payload": None,
                        "timeout": 10,
                        "response_format": "text",
                    },
                    "enabled": True,
                },
            )
        ],
    )
    subentry_id = next(
        sub.subentry_id
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_TYPE_TOOL
    )
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/schema",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
        }
    )
    msg = await client.receive_json()
    import json

    assert stored_secret not in json.dumps(msg)
    assert msg["result"]["data"]["headers"] == {"Authorization": ""}
    assert msg["result"]["headers_set"] == {"Authorization": True}


# --- 4. the MCP rebuild does not eat a subentry tool -----------------------


def _mcp_state(name: str, registered: list[str]):
    from custom_components.smartchain.tools.mcp.config import StdioConfig
    from custom_components.smartchain.tools.mcp.manager import _ServerState

    return _ServerState(config=StdioConfig(name=name, command="npx"), registered_names=registered)


async def test_stopping_mcp_does_not_delete_a_freshly_merged_tool(
    hass: HomeAssistant, tools_dir: Path
):
    """Order matters: `manager.stop()` deregisters by *name*.

    It used to run after `registry.replace_all(merged)`, so every name in its
    stale `registered_names` was stripped from the new registry — including a
    tool subentry that happened to share a name with a tool the previous MCP
    session had provided. The tool disappeared on the next rebuild with nothing
    logged.
    """
    (tools_dir / "tools.yaml").write_text("tools: []\nmcp_servers: []\n")
    await _entry(hass, [_tool_subentry("fs_read", _template_tool("mine, not the server's"))])

    from custom_components.smartchain import _reload_registry

    manager = hass.data[DOMAIN]["mcp_manager"]
    manager._servers = {"fs": _mcp_state("fs", ["fs_read"])}
    await _reload_registry(hass)

    tool = hass.data[DOMAIN]["tools"].get("fs_read")
    assert tool is not None
    assert tool.description == "mine, not the server's"


async def test_a_name_a_live_mcp_server_provides_is_refused_in_the_form(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Caught where it can be caught, which is at the point it is typed.

    MCP tools are discovered rather than declared, so this cannot be a
    guarantee — a server can announce the name tomorrow, which is what the
    ordering fix above and `_register_tools`'s own collision check are for. It
    is worth refusing the collision that is already visible.
    """
    (tools_dir / "tools.yaml").write_text("tools: []\nmcp_servers: []\n")
    entry = await _entry(hass)

    from custom_components.smartchain.tools.model import CustomTool, MCPAction

    registry = hass.data[DOMAIN]["tools"]
    registry.add(
        CustomTool(
            name="fs_read",
            description="from the server",
            parameters={"type": "object", "properties": {}},
            action=MCPAction(server="fs", tool_name="read", timeout=30),
        )
    )

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "data": {
                "name": "fs_read",
                "description": "Mine",
                "enabled": True,
                "action_type": "template",
                "params_mode": "simple",
                "params_rows": [],
                "value_template": "{{ 'ok' }}",
            },
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert "MCP" in msg["error"]["message"]
